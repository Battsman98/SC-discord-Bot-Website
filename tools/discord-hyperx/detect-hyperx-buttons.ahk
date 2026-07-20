#Requires AutoHotkey v2.0
#SingleInstance Force
#UseHook

TrayTip("HyperX detector running", "Press headset buttons, then press F12 for key history. Esc exits.", 8)

F12::{
    KeyHistory
}

Esc::{
    ExitApp
}
