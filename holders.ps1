# Which processes hold a directory open as their CURRENT DIRECTORY?
#
# * WHY THIS EXISTS. Windows refuses to rename a directory that is any live
# process's current directory, and the refusal is opaque: `mv` says "Device or
# resource busy", `Move-Item` says "Access is denied", and Restart Manager --
# the API built for exactly this question -- reports NO HOLDER, because RM
# tracks file handles and a current directory is not one. Measured 2026-08-20
# while renaming the ASIC repos: six processes held C:\dev\AIML_ASIC and
# nothing on the machine would name them.
#
# Reads each process's PEB -> RTL_USER_PROCESS_PARAMETERS -> CurrentDirectory.
# Processes owned by another user, or at higher integrity, are skipped rather
# than reported wrongly -- so an empty result means "none that this account can
# see", never "none".
#
#   powershell -File holders.ps1 C:\dev\spec2si-tsmc65
param([Parameter(Mandatory = $true)][string]$Path)

$src = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class CWDPROBE {
  [StructLayout(LayoutKind.Sequential)] struct PBI {
    public IntPtr R1; public IntPtr PebBaseAddress; public IntPtr R2; public IntPtr R3; public IntPtr Pid; public IntPtr R4;
  }
  [DllImport("ntdll.dll")] static extern int NtQueryInformationProcess(IntPtr h, int cls, ref PBI pbi, int len, out int ret);
  [DllImport("kernel32.dll")] static extern IntPtr OpenProcess(int access, bool inherit, int pid);
  [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr h);
  [DllImport("kernel32.dll")] static extern bool ReadProcessMemory(IntPtr h, IntPtr addr, byte[] buf, int size, out IntPtr read);
  // x64 offsets: PEB.ProcessParameters = 0x20; RTL_USER_PROCESS_PARAMETERS.CurrentDirectory.DosPath = 0x38
  public static string Get(int pid) {
    IntPtr h = OpenProcess(0x0400 | 0x0010, false, pid);
    if (h == IntPtr.Zero) return null;
    try {
      var pbi = new PBI(); int ret;
      if (NtQueryInformationProcess(h, 0, ref pbi, Marshal.SizeOf(pbi), out ret) != 0) return null;
      var b = new byte[8]; IntPtr got;
      if (!ReadProcessMemory(h, (IntPtr)((long)pbi.PebBaseAddress + 0x20), b, 8, out got)) return null;
      long pp = BitConverter.ToInt64(b, 0);
      var u = new byte[16];
      if (!ReadProcessMemory(h, (IntPtr)(pp + 0x38), u, 16, out got)) return null;
      int len = BitConverter.ToUInt16(u, 0); long buf = BitConverter.ToInt64(u, 8);
      if (len <= 0 || len > 4096) return null;
      var s = new byte[len];
      if (!ReadProcessMemory(h, (IntPtr)buf, s, len, out got)) return null;
      return Encoding.Unicode.GetString(s);
    } catch { return null; } finally { CloseHandle(h); }
  }
}
'@
Add-Type -TypeDefinition $src -Language CSharp -ErrorAction SilentlyContinue

$full = (Resolve-Path -LiteralPath $Path -ErrorAction SilentlyContinue)
if (-not $full) { Write-Host "no such path: $Path"; exit 2 }
$needle = $full.Path.TrimEnd('\')

$hits = @()
foreach ($p in Get-Process) {
  $d = $null
  try { $d = [CWDPROBE]::Get($p.Id) } catch { }
  if ($d -and $d.TrimEnd('\').StartsWith($needle, [StringComparison]::OrdinalIgnoreCase)) {
    $hits += [pscustomobject]@{ Pid = $p.Id; Name = $p.ProcessName; Cwd = $d.TrimEnd('\') }
  }
}
if ($hits.Count -eq 0) { Write-Host "   no process holds $needle as its current directory"; exit 0 }
Write-Host "   $($hits.Count) process(es) hold $needle as their CURRENT DIRECTORY:"
$hits | Sort-Object Name, Pid | ForEach-Object {
  Write-Host ("      pid={0,-7} {1,-12} {2}" -f $_.Pid, $_.Name, $_.Cwd)
}
$agents = @($hits | Where-Object { $_.Name -match 'claude|code' })
if ($agents.Count) {
  Write-Host ""
  $s = if ($agents.Count -eq 1) { "is an AGENT SESSION" } else { "are AGENT SESSIONS" }
  Write-Host "   !! $($agents.Count) of these $s. Close them -- including the one"
  Write-Host "      you may be reading this from -- then re-run. The shell helpers above"
  Write-Host "      belong to those sessions and go away with them."
}
exit 1
