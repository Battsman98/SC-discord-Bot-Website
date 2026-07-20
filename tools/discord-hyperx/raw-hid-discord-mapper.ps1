$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$source = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;
using System.Diagnostics;

public class HyperXDiscordMapper : Form
{
    private const int WM_INPUT = 0x00FF;
    private const int RID_INPUT = 0x10000003;
    private const int RIDI_DEVICENAME = 0x20000007;
    private const int RIM_TYPEKEYBOARD = 1;
    private const int RIM_TYPEHID = 2;
    private const int RIDEV_INPUTSINK = 0x00000100;
    private const int RIDI_DEVICEINFO = 0x2000000b;
    private const int SW_RESTORE = 9;

    private static DateTime lastMute = DateTime.MinValue;
    private static DateTime lastDeafen = DateTime.MinValue;
    private const bool ActivateDiscordBeforeSending = false;

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWINPUTDEVICE
    {
        public ushort usUsagePage;
        public ushort usUsage;
        public int dwFlags;
        public IntPtr hwndTarget;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWINPUTHEADER
    {
        public int dwType;
        public int dwSize;
        public IntPtr hDevice;
        public IntPtr wParam;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWINPUTDEVICELIST
    {
        public IntPtr hDevice;
        public uint dwType;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RID_DEVICE_INFO_HID
    {
        public uint cbSize;
        public uint dwType;
        public uint dwVendorId;
        public uint dwProductId;
        public uint dwVersionNumber;
        public ushort usUsagePage;
        public ushort usUsage;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWKEYBOARD
    {
        public ushort MakeCode;
        public ushort Flags;
        public ushort Reserved;
        public ushort VKey;
        public uint Message;
        public uint ExtraInformation;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct INPUT
    {
        public uint type;
        public KEYBDINPUT ki;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct KEYBDINPUT
    {
        public ushort wVk;
        public ushort wScan;
        public uint dwFlags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    private delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputDeviceList(RAWINPUTDEVICELIST[] devices, ref uint count, uint size);

    [DllImport("User32.dll", SetLastError=true)]
    private static extern bool RegisterRawInputDevices(RAWINPUTDEVICE[] devices, uint count, uint size);

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputData(IntPtr input, uint command, IntPtr data, ref uint size, uint headerSize);

    [DllImport("User32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    private static extern uint GetRawInputDeviceInfo(IntPtr device, uint command, StringBuilder data, ref uint size);

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputDeviceInfo(IntPtr device, uint command, IntPtr data, ref uint size);

    [DllImport("User32.dll")]
    private static extern IntPtr GetForegroundWindow();

    [DllImport("User32.dll")]
    private static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("User32.dll")]
    private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("User32.dll")]
    private static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);

    [DllImport("User32.dll")]
    private static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("User32.dll", CharSet=CharSet.Unicode)]
    private static extern int GetWindowText(IntPtr hWnd, StringBuilder text, int count);

    [DllImport("User32.dll", CharSet=CharSet.Unicode)]
    private static extern int GetClassName(IntPtr hWnd, StringBuilder className, int count);

    [DllImport("User32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint processId);

    [DllImport("User32.dll")]
    private static extern uint SendInput(uint nInputs, INPUT[] pInputs, int cbSize);

    public HyperXDiscordMapper()
    {
        this.Text = "HyperX Discord Mapper";
        this.Width = 520;
        this.Height = 120;
        this.ShowInTaskbar = true;

        var label = new Label();
        label.Dock = DockStyle.Fill;
        label.Text = "HyperX Discord mapper running. Close this window to stop.";
        label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
        this.Controls.Add(label);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);

        var deviceList = new System.Collections.Generic.List<RAWINPUTDEVICE>();
        AddRawInputRegistration(deviceList, 0x01, 0x06, this.Handle); // keyboard
        AddRawInputRegistration(deviceList, 0x0C, 0x01, this.Handle); // consumer controls
        AddRawInputRegistration(deviceList, 0x0B, 0x05, this.Handle); // headset

        foreach (var device in GetHyperXRawInputDevices())
        {
            AddRawInputRegistration(deviceList, device.Item1, device.Item2, this.Handle);
            Console.WriteLine("Registering HyperX HID usage page 0x{0:X4}, usage 0x{1:X4}", device.Item1, device.Item2);
        }

        RAWINPUTDEVICE[] devices = deviceList.ToArray();

        if (!RegisterRawInputDevices(devices, (uint)devices.Length, (uint)Marshal.SizeOf(typeof(RAWINPUTDEVICE))))
        {
            Console.WriteLine("RegisterRawInputDevices failed: " + Marshal.GetLastWin32Error());
        }
        else
        {
            Console.WriteLine("HyperX Discord mapper registered.");
            Console.WriteLine("0C-08 / VKey 0xB3 -> Ctrl+LeftShift+M");
            Console.WriteLine("0C-10 / VKey 0xB0 -> Ctrl+LeftShift+D");
        }
    }

    private static void AddRawInputRegistration(System.Collections.Generic.List<RAWINPUTDEVICE> deviceList, ushort usagePage, ushort usage, IntPtr handle)
    {
        bool exists = deviceList.Exists(x => x.usUsagePage == usagePage && x.usUsage == usage);
        if (exists) return;

        deviceList.Add(new RAWINPUTDEVICE { usUsagePage = usagePage, usUsage = usage, dwFlags = RIDEV_INPUTSINK, hwndTarget = handle });
    }

    private static System.Collections.Generic.List<Tuple<ushort, ushort>> GetHyperXRawInputDevices()
    {
        var result = new System.Collections.Generic.List<Tuple<ushort, ushort>>();
        uint count = 0;
        uint listSize = (uint)Marshal.SizeOf(typeof(RAWINPUTDEVICELIST));
        GetRawInputDeviceList(null, ref count, listSize);
        if (count == 0) return result;

        var devices = new RAWINPUTDEVICELIST[count];
        if (GetRawInputDeviceList(devices, ref count, listSize) == 0xFFFFFFFF) return result;

        foreach (var device in devices)
        {
            uint infoSize = (uint)Marshal.SizeOf(typeof(RID_DEVICE_INFO_HID));
            IntPtr infoPtr = Marshal.AllocHGlobal((int)infoSize);
            try
            {
                Marshal.WriteInt32(infoPtr, (int)infoSize);
                if (GetRawInputDeviceInfo(device.hDevice, RIDI_DEVICEINFO, infoPtr, ref infoSize) == 0xFFFFFFFF) continue;

                RID_DEVICE_INFO_HID info = Marshal.PtrToStructure<RID_DEVICE_INFO_HID>(infoPtr);
                if (info.dwVendorId == 0x03F0 && info.dwProductId == 0x0ABE)
                {
                    var tuple = Tuple.Create(info.usUsagePage, info.usUsage);
                    bool exists = result.Exists(x => x.Item1 == tuple.Item1 && x.Item2 == tuple.Item2);
                    if (!exists) result.Add(tuple);
                }
            }
            finally
            {
                Marshal.FreeHGlobal(infoPtr);
            }
        }

        return result;
    }

    protected override void WndProc(ref Message m)
    {
        if (m.Msg == WM_INPUT)
        {
            HandleRawInput(m.LParam);
        }

        base.WndProc(ref m);
    }

    private static string GetDeviceName(IntPtr device)
    {
        uint size = 0;
        GetRawInputDeviceInfo(device, RIDI_DEVICENAME, null, ref size);
        if (size == 0) return "";

        var sb = new StringBuilder((int)size);
        GetRawInputDeviceInfo(device, RIDI_DEVICENAME, sb, ref size);
        return sb.ToString();
    }

    private static void HandleRawInput(IntPtr rawInputHandle)
    {
        uint size = 0;
        uint headerSize = (uint)Marshal.SizeOf(typeof(RAWINPUTHEADER));
        GetRawInputData(rawInputHandle, RID_INPUT, IntPtr.Zero, ref size, headerSize);
        if (size == 0) return;

        IntPtr buffer = Marshal.AllocHGlobal((int)size);
        try
        {
            if (GetRawInputData(rawInputHandle, RID_INPUT, buffer, ref size, headerSize) != size) return;

            RAWINPUTHEADER header = Marshal.PtrToStructure<RAWINPUTHEADER>(buffer);
            IntPtr dataPtr = IntPtr.Add(buffer, Marshal.SizeOf(typeof(RAWINPUTHEADER)));
            string deviceName = GetDeviceName(header.hDevice).ToUpperInvariant();

            if (header.dwType == RIM_TYPEKEYBOARD)
            {
                RAWKEYBOARD keyboard = Marshal.PtrToStructure<RAWKEYBOARD>(dataPtr);
                bool keyDown = (keyboard.Flags & 0x01) == 0;
                if (!keyDown) return;

                if (keyboard.VKey == 0xB3) TriggerMute("keyboard 0xB3");
                if (keyboard.VKey == 0xB0) TriggerDeafen("keyboard 0xB0");
            }
            else if (header.dwType == RIM_TYPEHID && deviceName.Contains("VID_03F0") && deviceName.Contains("PID_0ABE"))
            {
                int dwSizeHid = Marshal.ReadInt32(dataPtr);
                int dwCount = Marshal.ReadInt32(IntPtr.Add(dataPtr, 4));
                int byteCount = Math.Max(0, dwSizeHid * dwCount);
                byte[] bytes = new byte[byteCount];
                Marshal.Copy(IntPtr.Add(dataPtr, 8), bytes, 0, byteCount);

                if (byteCount >= 2 && bytes[0] == 0x0C && bytes[1] == 0x08) TriggerMute("hid 0C-08");
                if (byteCount >= 2 && bytes[0] == 0x0C && bytes[1] == 0x10) TriggerDeafen("hid 0C-10");
                if (byteCount >= 2 && bytes[0] == 0x0C && bytes[1] == 0x00) Console.WriteLine(DateTime.Now.ToString("HH:mm:ss.fff") + " release ignored hid 0C-00");
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }

    private static void TriggerMute(string source)
    {
        if ((DateTime.Now - lastMute).TotalMilliseconds < 350) return;
        lastMute = DateTime.Now;
        Console.WriteLine(DateTime.Now.ToString("HH:mm:ss.fff") + " mute from " + source);
        SendDiscordCombo(0x4D); // M
    }

    private static void TriggerDeafen(string source)
    {
        if ((DateTime.Now - lastDeafen).TotalMilliseconds < 350) return;
        lastDeafen = DateTime.Now;
        Console.WriteLine(DateTime.Now.ToString("HH:mm:ss.fff") + " deafen from " + source);
        SendDiscordCombo(0x44); // D
    }

    private static IntPtr FindDiscordWindow()
    {
        IntPtr result = IntPtr.Zero;

        EnumWindows((hWnd, lParam) =>
        {
            if (!IsWindowVisible(hWnd)) return true;

            uint processId;
            GetWindowThreadProcessId(hWnd, out processId);
            if (processId == 0) return true;

            try
            {
                Process process = Process.GetProcessById((int)processId);
                if (process.ProcessName.Equals("Discord", StringComparison.OrdinalIgnoreCase))
                {
                    result = hWnd;
                    return false;
                }
            }
            catch
            {
                return true;
            }

            return true;
        }, IntPtr.Zero);

        return result;
    }

    private static void SendDiscordCombo(ushort key)
    {
        IntPtr previous = GetForegroundWindow();
        Console.WriteLine("Sending Ctrl+LeftShift+" + ((char)key).ToString() + " to active window 0x" + previous.ToString("X"));

        if (ActivateDiscordBeforeSending)
        {
            IntPtr discord = FindDiscordWindow();

            if (discord == IntPtr.Zero)
            {
                Console.WriteLine("Discord window not found.");
                return;
            }

            ShowWindow(discord, SW_RESTORE);
            SetForegroundWindow(discord);
            System.Threading.Thread.Sleep(80);
        }

        SendKeyDown(0x11); // Ctrl
        SendKeyDown(0xA0); // Left Shift
        SendKeyPress(key);
        SendKeyUp(0xA0);
        SendKeyUp(0x11);

        if (ActivateDiscordBeforeSending)
        {
            System.Threading.Thread.Sleep(80);
            if (previous != IntPtr.Zero) SetForegroundWindow(previous);
        }
    }

    private static void SendKeyPress(ushort vk)
    {
        SendKeyDown(vk);
        SendKeyUp(vk);
    }

    private static void SendKeyDown(ushort vk)
    {
        INPUT[] inputs = new INPUT[] { new INPUT { type = 1, ki = new KEYBDINPUT { wVk = vk, dwFlags = 0 } } };
        uint sent = SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
        if (sent != 1) Console.WriteLine("SendInput key down failed for 0x" + vk.ToString("X2"));
    }

    private static void SendKeyUp(ushort vk)
    {
        INPUT[] inputs = new INPUT[] { new INPUT { type = 1, ki = new KEYBDINPUT { wVk = vk, dwFlags = 2 } } };
        uint sent = SendInput(1, inputs, Marshal.SizeOf(typeof(INPUT)));
        if (sent != 1) Console.WriteLine("SendInput key up failed for 0x" + vk.ToString("X2"));
    }
}

public static class Program
{
    [STAThread]
    public static void Main()
    {
        Application.EnableVisualStyles();
        Application.Run(new HyperXDiscordMapper());
    }
}
'@

Add-Type -TypeDefinition $source -ReferencedAssemblies System.Windows.Forms,System.Drawing
[Program]::Main()
