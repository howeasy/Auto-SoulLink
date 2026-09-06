using System;
using BizHawk.Client.Common;
using BizHawk.Client.EmuHawk;

namespace SLink.Tests
{
    // Private probe adapter: queue a parameterless CLR action so any loader
    // exception is returned as evidence instead of a WinForms modal failure.
    public sealed class QuarantineLoader
    {
        private readonly ToolManager manager;
        private readonly string path;
        public QuarantineLoader(ToolManager manager, string path)
        {
            this.manager = manager;
            this.path = path;
        }
        public IExternalToolForm Result { get; private set; }
        public string Error { get; private set; }
        public bool Completed { get; private set; }
        public void Run()
        {
            try { Result = manager.LoadExternalToolForm(path, "SLink.Host.QuarantineGuard", false, true); }
            catch (Exception error) { Error = error.ToString(); }
            finally { Completed = true; }
        }
    }
}
