using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Threading;
using System.Windows.Forms;

using BizHawk.Client.Common;
using BizHawk.Client.EmuHawk;
using BizHawk.Emulation.Common;

namespace SLink.Host
{
	// This tool only retains an existing hold. It does not own or release the
	// platform_execution lease, and its nonce is an audit identifier, not a lease.
	[ExternalTool("SLink Quarantine Guard", Description = "Inactive experimental guard for an already-held mGBA process")]
	public sealed class QuarantineGuard : ToolFormBase, IExternalToolForm, IControlMainform
	{
		public const string ProtocolVersion = "slink-quarantine-held-v1";
		public const string ExpectedHostSha256 = "f8cdb93551a544f680bf3876d9d8d72643859e7a44a23b04e1a25b92e48f80cd";
		public const string ExpectedCoreType = "BizHawk.Emulation.Cores.Nintendo.GBA.MGBAHawk";
		public const string ExpectedCoreSha256 = "444bc157418e9b5df5d07e987fc7ad1d2d1c6993676f5b864368027cb4f054d5";
		public const string ExpectedNativeSha256 = "ba398a56e62ce1e4280fe96834cbbe4e6469b7070f34da313ec3d4637c4979e1";
		public const int RecordCapacity = 256;

		private readonly object _sync = new object();
		private readonly List<QuarantineRecord> _records = new List<QuarantineRecord>();
		private MainForm _retainedMainForm;
		private ToolManager _retainedTools;
		private IEmulator _retainedCore;
		private int _ownerThread;
		private int _initialFrame = -1;
		private string _requestNonce = "";
		private bool _arming;
		private bool _armed;
		private bool _failed;
		private string _failure = "";
		private bool _holdReadbackVerified;
		private long _sequence;
		private long _droppedRecords;

		public QuarantineGuard()
		{
			// FormBase owns Text through WindowTitle/UpdateWindowTitle.
			Width = 460;
			Height = 120;
			Controls.Add(new Label
			{
				Dock = DockStyle.Fill,
				Text = "Experimental quarantine only.\r\nExplicit arming requires an existing execution hold.\r\nThis tool has no release or resume action."
			});
		}

		protected override string WindowTitleStatic { get { return "SLink Quarantine Guard"; } }

		public bool QuarantineArm(string requestNonce)
		{
			lock (_sync)
			{
				if (_armed || _failed || _arming || !ValidNonce(requestNonce))
				{
					Append("arm", -1, "refused_invalid_request");
					return false;
				}

				MainForm host = MainForm as MainForm;
				try
				{
					if (host == null || host.GetType() != typeof(MainForm)
						|| Tools == null || !IsHandleCreated || IsDisposed || InvokeRequired
						|| !host.IsHandleCreated || host.IsDisposed || host.InvokeRequired
						|| host.Emulator == null || !host.BlockFrameAdvance)
					{
						Append("arm", -1, "refused_not_initialized_and_preheld");
						return false;
					}

					IEmulator core = host.Emulator;
					if (core.GetType().FullName != ExpectedCoreType || !CheckPinnedFiles(host, core))
					{
						Append("arm", -1, "refused_host_pins");
						return false;
					}

					// Temporarily participate in the public selector while validating it.
					// This section requests no emulation, UI-message pumping or yielding.
					// Other tools' property getters are not an arbitrary-code boundary.
					_arming = true;
					if (!SelectedByAll(Tools) || HasCompetingController(Tools)
						|| !ReferenceEquals(host.Emulator, core) || !host.BlockFrameAdvance)
					{
						Append("arm", -1, "refused_control_selection");
						return false;
					}

					_retainedMainForm = host;
					_retainedTools = Tools;
					_retainedCore = core;
					_ownerThread = Thread.CurrentThread.ManagedThreadId;
					_initialFrame = core.Frame;
					_requestNonce = requestNonce;
					_armed = true;
					_holdReadbackVerified = true;
					Append("arm", -1, "armed_existing_hold");
					return true;
				}
				catch (Exception ex)
				{
					Append("arm", -1, "refused_exception_" + ex.GetType().Name);
					return false;
				}
				finally { _arming = false; }
			}
		}

		public bool QuarantineVerify()
		{
			lock (_sync)
			{
				if (!_armed) return false;
				string reason = ContextFailure();
				if (reason.Length != 0) FaultAndHold(reason, "verify");
				else if (_failed) RetainHold();
				else _holdReadbackVerified = true;
				return !_failed && _holdReadbackVerified;
			}
		}

		public QuarantineStatus QuarantineStatus()
		{
			lock (_sync)
			{
				if (_armed) QuarantineVerify();
				bool selected = false;
				bool sameCore = false;
				bool blocked = false;
				bool readbackAvailable = false;
				int frame = -1;
				if (CanAccessRetainedHost())
				{
					try
					{
						blocked = _retainedMainForm.BlockFrameAdvance;
						readbackAvailable = true;
						frame = _retainedMainForm.Emulator.Frame;
						sameCore = ReferenceEquals(_retainedMainForm.Emulator, _retainedCore);
						selected = SelectedByAll(_retainedTools);
					}
					catch { readbackAvailable = false; }
				}
				return new QuarantineStatus(_armed, _failed, _failure, _requestNonce,
					_holdReadbackVerified && blocked && readbackAvailable, blocked,
					readbackAvailable, sameCore, selected, _initialFrame, frame,
					_sequence, _droppedRecords, _records.Count == 0 ? 0 : _records[0].Sequence);
			}
		}

		// Non-destructive read. Records are immutable; the returned array is a copy.
		public QuarantineRecord[] QuarantinePoll(long afterSequence)
		{
			lock (_sync)
			{
				List<QuarantineRecord> result = new List<QuarantineRecord>();
				foreach (QuarantineRecord record in _records)
					if (record.Sequence > afterSequence) result.Add(record);
				return result.ToArray();
			}
		}

		public override void Restart()
		{
			lock (_sync) { if (_armed) FaultAndHold("host_restart", "restart"); }
		}

		public override bool AskSaveChanges()
		{
			lock (_sync)
			{
				if (!_armed) return true;
				Deny("ask_save_changes", -1);
				return false;
			}
		}

		public override void UpdateValues(ToolFormUpdateType type)
		{
			// General updates can check the held process without admitting a frame.
			if (type == ToolFormUpdateType.General && _armed) QuarantineVerify();
		}

		protected override void OnFormClosing(FormClosingEventArgs e)
		{
			lock (_sync) { if (_armed) FaultAndHold("form_closing", "close"); }
			base.OnFormClosing(e);
		}

		protected override void Dispose(bool disposing)
		{
			lock (_sync) { if (_armed) FaultAndHold("form_disposed", "dispose"); }
			base.Dispose(disposing);
		}

		// An armed fault continues to participate; false would enable host fallback.
		public bool WantsToControlSavestates { get { return _armed || _arming; } }
		public bool WantsToControlRewind { get { return _armed || _arming; } }
		public bool WantsToControlReboot { get { return _armed || _arming; } }
		public bool LoadState() { Deny("load_state", -1); return false; }
		public bool LoadStateAs() { Deny("load_state_as", -1); return false; }
		public bool LoadQuickSave(int slot) { Deny("load_quick_save", slot); return false; }
		public void SaveState() { Deny("save_state", -1); }
		public void SaveStateAs() { Deny("save_state_as", -1); }
		public void SaveQuickSave(int slot) { Deny("save_quick_save", slot); }
		public void RebootCore() { Deny("reboot_core", -1); }
		public bool Rewind() { Deny("rewind", -1); return false; }
		public void CaptureRewind() { }
		public bool SelectSlot(int slot) { Deny("select_slot", slot); return _armed; }
		public bool PreviousSlot() { Deny("previous_slot", -1); return _armed; }
		public bool NextSlot() { Deny("next_slot", -1); return _armed; }
		public bool WantsToControlReadOnly { get { return false; } }
		public bool WantsToControlStopMovie { get { return false; } }
		public bool WantsToControlRestartMovie { get { return false; } }
		public bool WantsToBypassMovieEndAction { get { return false; } }
		public void ToggleReadOnly() { Deny("toggle_read_only_direct_call", -1); }
		public void StopMovie(bool suppressSave) { Deny("stop_movie_direct_call", -1); }
		public bool RestartMovie() { Deny("restart_movie_direct_call", -1); return false; }

		private void Deny(string action, int slot)
		{
			lock (_sync)
			{
				if (_armed)
				{
					string reason = ContextFailure();
					if (reason.Length != 0) LatchFailure(reason);
					if (!RetainHold()) LatchFailure("hold_readback_failed");
				}
				Append(action, slot, _armed ? "denied_not_performed" : "refused_unarmed");
			}
		}

		private string ContextFailure()
		{
			try
			{
				if (!CanAccessRetainedHost()) return "host_or_thread_unavailable";
				if (!ReferenceEquals(MainForm, _retainedMainForm)
					|| !ReferenceEquals(Tools, _retainedTools)) return "injected_host_changed";
				if (!ReferenceEquals(_retainedMainForm.Emulator, _retainedCore)) return "core_changed";
				if (!IsHandleCreated || IsDisposed) return "guard_inactive";
				if (!SelectedByAll(_retainedTools) || HasCompetingController(_retainedTools)) return "control_selection_lost";
				if (!_retainedMainForm.BlockFrameAdvance) return "existing_hold_lost";
				if (_retainedCore.Frame != _initialFrame) return "held_frame_changed";
				return "";
			}
			catch (Exception ex) { return "context_exception_" + ex.GetType().Name; }
		}

		private bool CanAccessRetainedHost()
		{
			return _retainedMainForm != null
				&& Thread.CurrentThread.ManagedThreadId == _ownerThread
				&& !_retainedMainForm.IsDisposed && _retainedMainForm.IsHandleCreated
				&& !_retainedMainForm.InvokeRequired;
		}

		private bool RetainHold()
		{
			_holdReadbackVerified = false;
			try
			{
				// Registration may already be gone (ToolManager.Close clears first).
				// A replacement core is never adopted; holding the retained main form
				// is still a useful emergency action while identity failure stays latched.
				if (!_armed || !CanAccessRetainedHost()) return false;
				bool paused = _retainedMainForm.EmulatorPaused;
				_retainedMainForm.BlockFrameAdvance = true;
				_holdReadbackVerified = _retainedMainForm.BlockFrameAdvance
					&& _retainedMainForm.EmulatorPaused == paused;
				return _holdReadbackVerified;
			}
			catch { return false; }
		}

		private void FaultAndHold(string reason, string action)
		{
			LatchFailure(reason);
			bool held = RetainHold();
			Append(action, -1, held ? "fault_hold_retained" : "fault_hold_unverified");
		}

		private void LatchFailure(string reason)
		{
			_failed = true;
			if (_failure.Length == 0) _failure = reason;
		}

		private void Append(string action, int slot, string outcome)
		{
			int frame = -1;
			bool blocked = false;
			try
			{
				if (CanAccessRetainedHost())
				{
					frame = _retainedMainForm.Emulator.Frame;
					blocked = _retainedMainForm.BlockFrameAdvance;
				}
			}
			catch { }
			if (_records.Count == RecordCapacity)
			{
				_records.RemoveAt(0);
				_droppedRecords++;
			}
			_records.Add(new QuarantineRecord(++_sequence, action, slot, frame,
				outcome, blocked, _holdReadbackVerified && blocked, _failed, _failure));
		}

		private bool SelectedByAll(ToolManager manager)
		{
			return manager != null
				&& ReferenceEquals(manager.FirstOrNull<IControlMainform>(delegate(IControlMainform t) { return t.WantsToControlSavestates; }), this)
				&& ReferenceEquals(manager.FirstOrNull<IControlMainform>(delegate(IControlMainform t) { return t.WantsToControlRewind; }), this)
				&& ReferenceEquals(manager.FirstOrNull<IControlMainform>(delegate(IControlMainform t) { return t.WantsToControlReboot; }), this);
		}

		private bool HasCompetingController(ToolManager manager)
		{
			return manager.FirstOrNull<IControlMainform>(delegate(IControlMainform t)
			{
				return !ReferenceEquals(t, this)
					&& (t.WantsToControlSavestates || t.WantsToControlRewind || t.WantsToControlReboot);
			}) != null;
		}

		private static bool ValidNonce(string value)
		{
			if (value == null || value.Length != 32) return false;
			foreach (char c in value)
				if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
			return true;
		}

		private static bool CheckPinnedFiles(MainForm host, IEmulator core)
		{
			using (Process process = Process.GetCurrentProcess())
			{
				string executable = process.MainModule.FileName;
				if (!String.Equals(Path.GetFullPath(host.GetType().Assembly.Location), Path.GetFullPath(executable), StringComparison.OrdinalIgnoreCase)
					|| HashFile(executable) != ExpectedHostSha256
					|| HashFile(core.GetType().Assembly.Location) != ExpectedCoreSha256) return false;
				int nativeMatches = 0;
				foreach (ProcessModule module in process.Modules)
				{
					if (!String.Equals(Path.GetFileName(module.FileName), "mgba.dll", StringComparison.OrdinalIgnoreCase)) continue;
					nativeMatches++;
					if (HashFile(module.FileName) != ExpectedNativeSha256) return false;
				}
				return nativeMatches == 1;
			}
		}

		private static string HashFile(string path)
		{
			using (SHA256 sha = SHA256.Create())
			using (FileStream stream = File.OpenRead(path))
				return BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "").ToLowerInvariant();
		}
	}

	public sealed class QuarantineRecord
	{
		public long Sequence { get; private set; }
		public string Action { get; private set; }
		public int Slot { get; private set; }
		public int Frame { get; private set; }
		public string Outcome { get; private set; }
		public bool HostBlocked { get; private set; }
		public bool HoldReadbackVerified { get; private set; }
		public bool Failed { get; private set; }
		public string Failure { get; private set; }
		internal QuarantineRecord(long sequence, string action, int slot, int frame,
			string outcome, bool blocked, bool held, bool failed, string failure)
		{
			Sequence = sequence; Action = action; Slot = slot; Frame = frame;
			Outcome = outcome; HostBlocked = blocked; HoldReadbackVerified = held;
			Failed = failed; Failure = failure;
		}
	}

	public sealed class QuarantineStatus
	{
		public string Protocol { get { return QuarantineGuard.ProtocolVersion; } }
		public bool Armed { get; private set; }
		public bool Failed { get; private set; }
		public string Failure { get; private set; }
		public string RequestNonce { get; private set; }
		public bool HoldReadbackVerified { get; private set; }
		public bool HostBlocked { get; private set; }
		public bool HoldReadbackAvailable { get; private set; }
		public bool OriginalCore { get; private set; }
		public bool SelectedForAllControls { get; private set; }
		public int InitialFrame { get; private set; }
		public int CurrentFrame { get; private set; }
		public long LastSequence { get; private set; }
		public long DroppedRecords { get; private set; }
		public long FirstRetainedSequence { get; private set; }
		public bool QuarantineOnly { get { return true; } }
		public bool FullExecutionSafety { get { return false; } }
		public bool ProductionSelected { get { return false; } }
		internal QuarantineStatus(bool armed, bool failed, string failure, string nonce,
			bool held, bool blocked, bool available, bool originalCore, bool selected,
			int initialFrame, int frame, long sequence, long dropped, long first)
		{
			Armed = armed; Failed = failed; Failure = failure; RequestNonce = nonce;
			HoldReadbackVerified = held; HostBlocked = blocked; HoldReadbackAvailable = available;
			OriginalCore = originalCore; SelectedForAllControls = selected;
			InitialFrame = initialFrame; CurrentFrame = frame; LastSequence = sequence;
			DroppedRecords = dropped; FirstRetainedSequence = first;
		}
	}
}
