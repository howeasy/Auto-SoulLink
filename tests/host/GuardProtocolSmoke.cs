using System;
using System.IO;
using System.Reflection;

public static class GuardProtocolSmoke
{
    private static int checks;
    private static void Check(bool value, string label)
    {
        checks++;
        if (!value) throw new Exception(label);
    }
    private static object Get(object value, string property)
    {
        return value.GetType().GetProperty(property).GetValue(value, null);
    }
    private static object Call(object value, string method, params object[] args)
    {
        return value.GetType().GetMethod(method).Invoke(value, args);
    }
    [STAThread]
    public static int Main(string[] args)
    {
        try
        {
            string host = Path.GetFullPath(args[0]);
            AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs request)
            {
                string name = new AssemblyName(request.Name).Name;
                string file = Path.Combine(host, name == "EmuHawk" || name == "BizHawk.Client.EmuHawk" ? "EmuHawk.exe" : "dll/" + name + ".dll");
                return File.Exists(file) ? Assembly.LoadFrom(file) : null;
            };
            Type type = Assembly.LoadFrom(Path.GetFullPath(args[1])).GetType("SLink.Host.QuarantineGuard", true);
            object guard = Activator.CreateInstance(type);
            Check((bool)Call(guard, "QuarantineArm", new string('a',32)) == false, "uninitialized foreign process cannot arm");
            Check((bool)Call(guard, "LoadState") == false, "unarmed named load refused");
            Check((bool)Call(guard, "LoadQuickSave", 3) == false, "unarmed quick load refused");
            Check((bool)Call(guard, "Rewind") == false, "unarmed rewind refused");
            Call(guard, "RebootCore");
            object status = Call(guard, "QuarantineStatus");
            Check(!(bool)Get(status,"Armed") && !(bool)Get(status,"HoldReadbackAvailable"), "unarmed status does not invent host");
            Check((bool)Get(status,"QuarantineOnly") && !(bool)Get(status,"FullExecutionSafety") && !(bool)Get(status,"ProductionSelected"), "scope stays unavailable");
            Array records = (Array)Call(guard, "QuarantinePoll", 0L);
            Check(records.Length == 5, "five explicit refusals retained");
            object first = records.GetValue(0);
            foreach (PropertyInfo property in first.GetType().GetProperties())
                Check(property.GetSetMethod() == null, "record property publicly mutable: " + property.Name);
            records.SetValue(null,0);
            Check(((Array)Call(guard,"QuarantinePoll",0L)).GetValue(0) != null, "poll array detached");
            Call(guard,"CaptureRewind");
            Check(((Array)Call(guard,"QuarantinePoll",0L)).Length == 5, "frame capture is not a rewind request");
            for (int i=0;i<300;i++) Call(guard,"LoadQuickSave",i);
            records = (Array)Call(guard,"QuarantinePoll",0L);
            status = Call(guard,"QuarantineStatus");
            Check(records.Length==256, "record capacity enforced");
            Check((long)Get(status,"DroppedRecords")==49L, "dropped records explicit");
            Check((long)Get(status,"FirstRetainedSequence")==50L && (long)Get(status,"LastSequence")==305L, "cursor gap observable");
            Check(((Array)Call(guard,"QuarantinePoll",304L)).Length==1, "cursor is non-destructive");
            ((IDisposable)guard).Dispose();
            Console.WriteLine("{\"checks\":" + checks + ",\"scope\":\"compiled unarmed protocol; no emulator or routing proof\"}");
            return 0;
        }
        catch(Exception error) { Console.Error.WriteLine(error); return 1; }
    }
}
