// Frivo's native Windows host.
//
// It runs the existing PowerShell installer/launcher scripts in-process,
// rather than starting powershell.exe. That preserves the mature setup logic
// while giving Windows and Task Manager a real Frivo executable to display.

using System;
using System.IO;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Frivo")]
[assembly: AssemblyDescription("Frivo desktop host")]
[assembly: AssemblyCompany("Frivo")]
[assembly: AssemblyProduct("Frivo")]
[assembly: AssemblyVersion("1.1.0.0")]
[assembly: AssemblyFileVersion("1.1.0.0")]

internal static class Program
{
    [STAThread]
    private static int Main(string[] args)
    {
        string script = null;
        string dataPath = null;
        string tray = null;

        for (var index = 0; index < args.Length; index++)
        {
            var argument = args[index];
            if (string.Equals(argument, "--script", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
                script = args[++index];
            else if (string.Equals(argument, "--data", StringComparison.OrdinalIgnoreCase) && index + 1 < args.Length)
                dataPath = args[++index];
            else if (string.Equals(argument, "--tray", StringComparison.OrdinalIgnoreCase))
                tray = "true";
        }

        if (string.IsNullOrWhiteSpace(script) || !File.Exists(script))
        {
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
                    powerShell.AddCommand(script);
                    if (!string.IsNullOrWhiteSpace(dataPath))
                        powerShell.AddParameter("DataPath", dataPath);
                    if (tray != null)
                        powerShell.AddParameter("Tray");

                    powerShell.Invoke();
                    if (powerShell.HadErrors)
                    {
                        var message = "Frivo could not start.";
                        if (powerShell.Streams.Error.Count > 0)
                            message += "\r\n\r\n" + powerShell.Streams.Error[0].ToString();
                        MessageBox.Show(message, "Frivo", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return 1;
                    }
                }
            }
            return 0;
        }
        catch (Exception exception)
        {
            MessageBox.Show("Frivo could not start.\r\n\r\n" + exception.Message,
                "Frivo", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
