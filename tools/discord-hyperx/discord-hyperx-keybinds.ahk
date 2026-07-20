#Requires AutoHotkey v2.0
#SingleInstance Force
#UseHook

; Discord keybind targets. Configure these same combos in Discord:
; Toggle Mute   -> Ctrl+Left Shift+M
; Toggle Deafen -> Ctrl+Left Shift+D
; Push to Talk  -> Ctrl+Alt+Shift+F15

SendDiscordMute() {
    SendDiscordCombo("m")
}

SendDiscordDeafen() {
    SendDiscordCombo("d")
}

SendDiscordPushToTalkTap() {
    SendInput("^!+{F15}")
}

SendDiscordCombo(key) {
    previousWindow := WinExist("A")
    discordWindow := WinExist("ahk_exe Discord.exe")

    if (!discordWindow) {
        TrayTip("Discord HyperX keybinds", "Discord.exe window was not found.", 5)
        return
    }

    WinActivate(discordWindow)
    if (!WinWaitActive(discordWindow, , 1)) {
        TrayTip("Discord HyperX keybinds", "Could not activate Discord window.", 5)
        return
    }

    SendEvent("{Ctrl down}{LShift down}" key "{LShift up}{Ctrl up}")

    if (previousWindow && WinExist("ahk_id " previousWindow)) {
        WinActivate("ahk_id " previousWindow)
    }
}

; HyperX Cloud Alpha 2 Wireless dongle events observed through Raw Input:
; vkB3 = media play/pause -> Discord mute
; vkB0 = media next track  -> Discord deafen
vkB3::SendDiscordMute()
vkB0::SendDiscordDeafen()
Media_Play_Pause::SendDiscordMute()
Media_Next::SendDiscordDeafen()

; Keep this as a fallback for other headset/media buttons.
Launch_App2::SendDiscordPushToTalkTap()

; If the detector shows a raw key code, add it like this:
; vkADsc120::SendDiscordMute()

TrayTip("Discord HyperX keybinds running", "vkB3=Ctrl+LShift+M, vkB0=Ctrl+LShift+D.", 8)
