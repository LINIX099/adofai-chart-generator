# Screenshot the LARGEST visible electron window (main window vs 660x520 welcome window).
#   powershell -ExecutionPolicy Bypass -File tools\_shotmain.ps1 -Out x.png [-Wait 0.8]
# NOTE: ASCII only -- Windows PowerShell 5.1 reads .ps1 as GBK and a CJK string eats the quote.
param([string]$Out = "$env:TEMP\main.png", [double]$Wait = 0.8)

Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class MW {
  public delegate bool Proc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] public static extern bool EnumWindows(Proc cb, IntPtr l);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  public static long[] Best(uint[] pids) {
    long[] res = new long[5];      // hwnd, w, h, x, y  (lambda cannot use out/ref)
    int area = 0;
    EnumWindows((hh, l) => {
      if (!IsWindowVisible(hh)) return true;
      var sb = new StringBuilder(512); GetWindowTextW(hh, sb, 512);
      if (sb.Length == 0) return true;
      uint pid; GetWindowThreadProcessId(hh, out pid);
      bool want = false; foreach (var p in pids) if (p == pid) want = true;
      if (!want) return true;
      RECT r; GetWindowRect(hh, out r);
      int a = (r.R - r.L) * (r.B - r.T);
      if (a > area) {
        area = a;
        res[0] = hh.ToInt64(); res[1] = r.R - r.L; res[2] = r.B - r.T; res[3] = r.L; res[4] = r.T;
      }
      return true;
    }, IntPtr.Zero);
    return res;
  }
}
"@
$pids = [uint32[]]((Get-Process electron -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id))
if (-not $pids) { Write-Output "no electron process"; exit 1 }
$res = [MW]::Best($pids)
$hw = [IntPtr]$res[0]
$w = $res[1]; $h = $res[2]; $x0 = $res[3]; $y0 = $res[4]
if ($hw -eq [IntPtr]::Zero) { Write-Output "no visible window"; exit 1 }
Write-Output ("MAIN hwnd={0}  {1}x{2} @({3},{4})" -f $hw, $w, $h, $x0, $y0)

$TOPMOST = 0x0002 -bor 0x0001 -bor 0x0040
[void][MW]::ShowWindow($hw, 9)
[void][MW]::SetWindowPos($hw, [IntPtr](-1), 0, 0, 0, 0, $TOPMOST)
Start-Sleep -Milliseconds ([int](1000 * $Wait))
[void][MW]::SetWindowPos($hw, [IntPtr](-1), 0, 0, 0, 0, $TOPMOST)
Start-Sleep -Milliseconds 400

$b = [System.Windows.Forms.SystemInformation]::VirtualScreen
$bmp = New-Object System.Drawing.Bitmap($b.Width, $b.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($b.Left, $b.Top, 0, 0, $bmp.Size)
$g.Dispose()
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
[void][MW]::SetWindowPos($hw, [IntPtr](-2), 0, 0, 0, 0, 0x0002 -bor 0x0001)
Write-Output ("saved " + $Out)
