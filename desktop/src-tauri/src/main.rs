// Prevents additional console window on Windows in release
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod menubar;

use tauri::Manager;

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            // Setup menu bar tray
            let _tray = menubar::create_tray(app.handle())?;
            // Register global shortcut: Cmd+Shift+Space
            menubar::register_shortcut(app.handle())?;
            Ok(())
        })
        .on_window_event(|window, event| {
            // Hide to tray on close instead of quitting
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if let Some(win) = window.get_window("main") {
                    win.hide().ok();
                    api.prevent_close();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running agent desktop");
}
