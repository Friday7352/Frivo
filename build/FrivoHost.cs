// Native Windows host for Frivo's PowerShell UI scripts.

using System;
using System.IO;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Frivo")]
[assembly: AssemblyDescription("Frivo desktop host")]
[assembly: AssemblyCompany("Friday")]
[assembly: AssemblyProduct("Frivo")]
[assembly: AssemblyVersion("1.1.1.0")]
[assembly: AssemblyFileVersion("1.1.1.0")]

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string script = null;
        string dataPath = null;
        string tray = null;
        // NEW (updates): an in-app update runs setup as SYSTEM with no
        // desktop. --silent passes -Silent to the script and never shows a
        // message box: a box nobody can see would wait for ever, and setup
        // with it. The script logs its own reason; the exit code says it
        // failed. --action picks Install.ps1's -Action (Update for updates).
        bool silent = false;
        string action = null;

        for (var index = 0; index < args.Length; index++)
        {
            var argument = args[index];
            if (string.Equals(argument, "--script", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
                script = args[++index];
            else if (string.Equals(argument, "--data", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
                dataPath = args[++index];
            else if (string.Equals(argument, "--tray", StringComparison.OrdinalIgnoreCase))
                tray = "true";
            else if (string.Equals(argument, "--silent", StringComparison.OrdinalIgnoreCase))   // NEW (updates)
                silent = true;
            else if (string.Equals(argument, "--action", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)   // NEW (updates)
                action = args[++index];
        }

        if (string.IsNullOrWhiteSpace(script) || !File.Exists(script))
        {
            if (!silent)
                MessageBox.Show("Frivo's startup script could not be found.", "Frivo",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }

        try
        {
            Directory.SetCurrentDirectory(Path.GetDirectoryName(Path.GetFullPath(script)));

            using (var runspace = RunspaceFactory.CreateRunspace())
            {
                runspace.ApartmentState = System.Threading.ApartmentState.STA;
                runspace.ThreadOptions = PSThreadOptions.ReuseThread;
                runspace.Open();

                using (var powerShell = PowerShell.Create())
                {
                    powerShell.Runspace = runspace;

                    // Bundled Frivo scripts must run regardless of the user's
                    // LocalMachine or CurrentUser execution-policy setting.
                    powerShell.AddScript("Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force");
                    powerShell.Invoke();
                    if (powerShell.HadErrors)
                        throw new InvalidOperationException("Unable to set the process execution policy.");
                    powerShell.Commands.Clear();
                    powerShell.Streams.Error.Clear();

                    powerShell.AddCommand(script);
                    if (!string.IsNullOrWhiteSpace(dataPath))
                        powerShell.AddParameter("DataPath", dataPath);
                    if (tray != null)
                        powerShell.AddParameter("Tray");
                    if (silent)   // NEW (updates)
                        powerShell.AddParameter("Silent");
                    if (!string.IsNullOrWhiteSpace(action))   // NEW (updates)
                        powerShell.AddParameter("Action", action);

                    powerShell.Invoke();
                    if (powerShell.HadErrors)
                    {
                        var message = "Frivo could not start.";
                        if (powerShell.Streams.Error.Count > 0)
                            message += "\r\n\r\n" + powerShell.Streams.Error[0].ToString();
                        if (!silent)   // CHANGED (updates)
                            MessageBox.Show(message, "Frivo", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return 1;
                    }
                }
            }
            return 0;
        }
        catch (Exception exception)
        {
            if (!silent)   // CHANGED (updates)
                MessageBox.Show("Frivo could not start.\r\n\r\n" + exception.Message,
                    "Frivo", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
