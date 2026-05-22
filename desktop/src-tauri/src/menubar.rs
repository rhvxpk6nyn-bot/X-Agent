use tauri::{
    AppHandle, Manager, Runtime,
    menu::{MenuBuilder, MenuItemBuilder},
    tray::{TrayIconBuilder, TrayIconEvent, MouseButton, MouseButtonState},
};

pub fn create_tray<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    let toggle = MenuItemBuilder::with_id("toggle", "Show/Hide").build(app)?;
    let quit = MenuItemBuilder::with_id("quit", "Quit").build(app)?;

    let menu = MenuBuilder::new(app)
        .item(&toggle)
        .separator()
        .item(&quit)
        .build()?;

    let _tray = TrayIconBuilder::new()
        .icon(app.default_window_icon().unwrap().clone())
        .menu(&menu)
        .tooltip("Agent")
        .on_menu_event(|app, event| {
            match event.id().as_ref() {
                "toggle" => toggle_window(app),
                "quit" => app.exit(0),
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            // Left-click tray icon to toggle window
            if matches!(event, TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            }) {
                toggle_window(tray.app_handle());
            }
        })
        .build(app)?;

    Ok(())
}

fn toggle_window<R: Runtime>(app: &AppHandle<R>) {
    if let Some(win) = app.get_webview_window("main") {
        match win.is_visible() {
            Ok(true) => { win.hide().ok(); }
            _ => {
                win.show().ok();
                win.set_focus().ok();
            }
        }
    }
}

pub fn register_shortcut<R: Runtime>(app: &AppHandle<R>) -> tauri::Result<()> {
    // Register via tauri global-shortcut plugin
    // Cmd+Shift+Space toggles the agent window
    #[cfg(target_os = "macos")]
    {
        use tauri_plugin_global_shortcut::GlobalShortcutExt;
        let app_h = app.clone();
        app_h.plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(move |_app, shortcut, _event| {
                    if shortcut.to_string() == "CommandOrControl+Shift+Space" {
                        toggle_window(&app_h);
                    }
                })
                .build(),
        )?;
    }
    Ok(())
}
