#Requires AutoHotkey v2.0
#SingleInstance Force
#UseHook

; HyperX Cloud Alpha 2 Wireless pause/resume button is exposed to Windows as
; Media_Play_Pause / vkB3. This intercepts it before Chrome/YouTube sees it.
; Discord should bind Toggle Deafen to F13.

logFile := A_ScriptDir "\hyperx-discord-mapper.log"

Log(message) {
    global logFile
    FileAppend(FormatTime(, "yyyy-MM-dd HH:mm:ss") " " message "`n", logFile)
}

SendDiscordDeafen() {
    Log("Button caught: sending Discord deafen")
    ToolTip("HyperX media button -> Discord deafen")
    SetTimer(() => ToolTip(), -900)

    previousWindow := WinExist("A")
    previousTitle := previousWindow ? WinGetTitle("ahk_id " previousWindow) : ""
    discordWindow := WinExist("ahk_exe Discord.exe")
    if (!discordWindow) {
        discordWindow := WinExist("ahk_exe DiscordPTB.exe")
    }
    if (!discordWindow) {
        discordWindow := WinExist("ahk_exe DiscordCanary.exe")
    }

    if (!discordWindow) {
        Log("Discord window not found")
        TrayTip("HyperX Discord deafen", "Discord.exe window was not found.", 5)
        return
    }

    Log("Previous window: " previousTitle)
    Log("Discord window found: " WinGetTitle("ahk_id " discordWindow))
    WinActivate("ahk_id " discordWindow)
    if (!WinWaitActive("ahk_id " discordWindow, , 1)) {
        Log("Could not activate Discord")
        TrayTip("HyperX Discord deafen", "Could not activate Discord.", 5)
        return
    }

    Sleep(120)
    Log("Sending F13")
    SendMode("Event")
    SetKeyDelay(50, 50)
    Send("{F13}")
    Sleep(80)

    if (previousWindow && WinExist("ahk_id " previousWindow)) {
        WinActivate("ahk_id " previousWindow)
        Log("Returned to previous window")
    }
}

QueueDiscordDeafen() {
    Log("Media hotkey caught: queueing deafen")
    SetTimer(SendDiscordDeafen, -120)
}

Media_Play_Pause::QueueDiscordDeafen()
vkB3::QueueDiscordDeafen()
F9::SendDiscordDeafen()

Esc::ExitApp()

Log("Mapper started")
TrayTip("HyperX Discord deafen v3 running", "Pause/resume/F9 now sends F13. Bind Discord deafen to F13.", 8)
