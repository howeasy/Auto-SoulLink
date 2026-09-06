using System;
using System.IO;
using System.Reflection;
using System.Runtime.InteropServices;

// Standalone pinned-NLua interop reproduction. No MainForm, emulator or guard.
public sealed class BindingFixture
{
    public int Calls { get; private set; }
    public long Echo(long value) { Calls++; return value; }
}

public static class NLuaBindingSmoke
{
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static extern bool SetDllDirectory(string path);

    public static int Main(string[] args)
    {
        object lua = null;
        try
        {
            string dll = Path.Combine(Path.GetFullPath(args[0]), "dll");
            if (!SetDllDirectory(dll)) throw new Exception("DLL directory unavailable");
            AppDomain.CurrentDomain.AssemblyResolve += delegate(object sender, ResolveEventArgs request)
            {
                string file = Path.Combine(dll, new AssemblyName(request.Name).Name + ".dll");
                return File.Exists(file) ? Assembly.LoadFrom(file) : null;
            };
            Type type = Assembly.LoadFrom(Path.Combine(dll, "NLua.dll")).GetType("NLua.Lua", true);
            lua = Activator.CreateInstance(type, new object[] { true });
            BindingFixture fixture = new BindingFixture();
            type.GetProperty("Item", new Type[] { typeof(string) }).SetValue(lua, fixture, new object[] { "fixture" });
            string script = @"
                assert(fixture:Echo(1) == 1)
                local ok, why = pcall(function() return fixture:Echo(2) end)
                assert(not ok and tostring(why):find('Argument number 1 is invalid', 1, true))
                assert(fixture.Calls == 1)
                local bound = luanet.get_method_bysig(fixture, 'Echo', 'System.Int64')
                for i = 2, 101 do assert(bound(i) == i) end
                assert(fixture.Calls == 101)
                return true
            ";
            object[] result = (object[])type.GetMethod("DoString", new Type[] { typeof(string), typeof(string) })
                .Invoke(lua, new object[] { script, "pinned_binding_reproduction" });
            if (result.Length != 1 || !(result[0] is bool) || !(bool)result[0]) throw new Exception("missing result");
            Console.WriteLine("{\"named_repeat_failed_before_call\":true,\"signature_calls\":100,\"emulator_launched\":false}");
            return 0;
        }
        catch (Exception error) { Console.Error.WriteLine(error); return 1; }
        finally { if (lua is IDisposable) ((IDisposable)lua).Dispose(); }
    }
}
