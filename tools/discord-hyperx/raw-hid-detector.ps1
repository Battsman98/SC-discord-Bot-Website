$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms

$source = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

public class RawInputWindow : Form
{
    private const int WM_INPUT = 0x00FF;
    private const int RID_INPUT = 0x10000003;
    private const int RIDI_DEVICENAME = 0x20000007;
    private const int RIM_TYPEMOUSE = 0;
    private const int RIM_TYPEKEYBOARD = 1;
    private const int RIM_TYPEHID = 2;
    private const int RIDEV_INPUTSINK = 0x00000100;
    private const int RIDI_DEVICEINFO = 0x2000000b;

    [StructLayout(LayoutKind.Sequential)]
    private struct RAWINPUTDEVICE
    {
        public ushort usUsagePage;
        public ushort usUsage;
        public int dwFlags;
        public IntPtr hwndTarget;
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
    private struct RAWINPUTHEADER
    {
        public int dwType;
        public int dwSize;
        public IntPtr hDevice;
        public IntPtr wParam;
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

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputDeviceList(
        [Out] RAWINPUTDEVICELIST[] pRawInputDeviceList,
        ref uint puiNumDevices,
        uint cbSize
    );

    [DllImport("User32.dll", SetLastError=true)]
    private static extern bool RegisterRawInputDevices(
        RAWINPUTDEVICE[] pRawInputDevices,
        uint uiNumDevices,
        uint cbSize
    );

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputData(
        IntPtr hRawInput,
        uint uiCommand,
        IntPtr pData,
        ref uint pcbSize,
        uint cbSizeHeader
    );

    [DllImport("User32.dll", SetLastError=true, CharSet=CharSet.Unicode)]
    private static extern uint GetRawInputDeviceInfo(
        IntPtr hDevice,
        uint uiCommand,
        StringBuilder pData,
        ref uint pcbSize
    );

    [DllImport("User32.dll", SetLastError=true)]
    private static extern uint GetRawInputDeviceInfo(
        IntPtr hDevice,
        uint uiCommand,
        IntPtr pData,
        ref uint pcbSize
    );

    public RawInputWindow()
    {
        this.Text = "HyperX Raw HID Detector";
        this.Width = 720;
        this.Height = 140;
        this.ShowInTaskbar = true;

        var label = new Label();
        label.Dock = DockStyle.Fill;
        label.Text = "Raw HID detector running. Press HyperX headset/dongle buttons, then watch the PowerShell output. Close this window to stop.";
        label.TextAlign = System.Drawing.ContentAlignment.MiddleCenter;
        this.Controls.Add(label);
    }

    protected override void OnHandleCreated(EventArgs e)
    {
        base.OnHandleCreated(e);

        var deviceList = new System.Collections.Generic.List<RAWINPUTDEVICE>();
        deviceList.Add(new RAWINPUTDEVICE { usUsagePage = 0x01, usUsage = 0x06, dwFlags = RIDEV_INPUTSINK, hwndTarget = this.Handle }); // keyboard
        deviceList.Add(new RAWINPUTDEVICE { usUsagePage = 0x0C, usUsage = 0x01, dwFlags = RIDEV_INPUTSINK, hwndTarget = this.Handle }); // consumer controls
        deviceList.Add(new RAWINPUTDEVICE { usUsagePage = 0x0B, usUsage = 0x05, dwFlags = RIDEV_INPUTSINK, hwndTarget = this.Handle }); // headset

        foreach (var device in GetHyperXRawInputDevices())
        {
            deviceList.Add(new RAWINPUTDEVICE { usUsagePage = device.Item1, usUsage = device.Item2, dwFlags = RIDEV_INPUTSINK, hwndTarget = this.Handle });
            Console.WriteLine("Registering HyperX HID usage page 0x{0:X4}, usage 0x{1:X4}", device.Item1, device.Item2);
        }

        RAWINPUTDEVICE[] devices = deviceList.ToArray();

        if (!RegisterRawInputDevices(devices, (uint)devices.Length, (uint)Marshal.SizeOf(typeof(RAWINPUTDEVICE))))
        {
            Console.WriteLine("RegisterRawInputDevices failed: " + Marshal.GetLastWin32Error());
        }
        else
        {
            Console.WriteLine("Raw HID detector registered. Press HyperX buttons now.");
        }
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
        if (size == 0) return "(unknown device)";

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
            string deviceName = GetDeviceName(header.hDevice);
            string kind = header.dwType == RIM_TYPEKEYBOARD ? "KEYBOARD" : header.dwType == RIM_TYPEHID ? "HID" : header.dwType == RIM_TYPEMOUSE ? "MOUSE" : "OTHER";

            IntPtr dataPtr = IntPtr.Add(buffer, Marshal.SizeOf(typeof(RAWINPUTHEADER)));

            if (header.dwType == RIM_TYPEKEYBOARD)
            {
                RAWKEYBOARD keyboard = Marshal.PtrToStructure<RAWKEYBOARD>(dataPtr);
                Console.WriteLine("{0:HH:mm:ss.fff} {1} VKey=0x{2:X2} Scan=0x{3:X2} Flags=0x{4:X2} Device={5}",
                    DateTime.Now, kind, keyboard.VKey, keyboard.MakeCode, keyboard.Flags, deviceName);
            }
            else if (header.dwType == RIM_TYPEHID)
            {
                int dwSizeHid = Marshal.ReadInt32(dataPtr);
                int dwCount = Marshal.ReadInt32(IntPtr.Add(dataPtr, 4));
                int byteCount = Math.Max(0, dwSizeHid * dwCount);
                byte[] bytes = new byte[byteCount];
                Marshal.Copy(IntPtr.Add(dataPtr, 8), bytes, 0, byteCount);
                Console.WriteLine("{0:HH:mm:ss.fff} {1} Size={2} Count={3} Data={4} Device={5}",
                    DateTime.Now, kind, dwSizeHid, dwCount, BitConverter.ToString(bytes), deviceName);
            }
        }
        finally
        {
            Marshal.FreeHGlobal(buffer);
        }
    }
}

public static class Program
{
    [STAThread]
    public static void Main()
    {
        Application.EnableVisualStyles();
        Application.Run(new RawInputWindow());
    }
}
'@

Add-Type -TypeDefinition $source -ReferencedAssemblies System.Windows.Forms,System.Drawing
[Program]::Main()
