use serde::Serialize;
use tauri::{Emitter, Manager};
use tauri_plugin_store::StoreExt;

mod python_manager;

// 给前端的响应格式
#[derive(Serialize)]
struct PythonStatus {
    running: bool,
    port: u16,
}

#[derive(Serialize)]
struct ApiResponse<T> {
    success: bool,
    data: Option<T>,
    error: Option<String>,
}

// ========== Tauri Commands ==========

/// 启动 Python 后端
#[tauri::command]
async fn start_python() -> Result<ApiResponse<u16>, String> {
    match python_manager::start_python_backend().await {
        Ok(port) => {
            Ok(ApiResponse {
                success: true,
                data: Some(port),
                error: None,
            })
        }
        Err(e) => Ok(ApiResponse {
            success: false,
            data: None,
            error: Some(e),
        }),
    }
}

/// 停止 Python 后端
#[tauri::command]
async fn stop_python() -> Result<ApiResponse<String>, String> {
    python_manager::stop_python_backend().await;
    Ok(ApiResponse {
        success: true,
        data: Some("已停止".to_string()),
        error: None,
    })
}

/// 获取 Python 状态
#[tauri::command]
async fn get_python_status() -> Result<PythonStatus, String> {
    let running = python_manager::is_python_running().await;
    let port = python_manager::get_python_port();
    Ok(PythonStatus { running, port })
}

/// 获取 Python 服务地址（前端用来连接 WebSocket）
#[tauri::command]
fn get_python_url() -> String {
    let port = python_manager::get_python_port();
    if port == 0 {
        String::new()
    } else {
        format!("ws://127.0.0.1:{}/ws/chat", port)
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_store::Builder::new().build())
        .invoke_handler(tauri::generate_handler![
            start_python,
            stop_python,
            get_python_status,
            get_python_url,
        ])
        .setup(|app| {
            let app_handle = app.handle().clone();

            // 加载保存的窗口大小（如果有）
            if let Ok(store) = app_handle.store("settings.json") {
                let saved_width: Option<u32> = store.get("window_width").and_then(|v| v.as_u64()).map(|v| v as u32);
                let saved_height: Option<u32> = store.get("window_height").and_then(|v| v.as_u64()).map(|v| v as u32);

                if let Some(window) = app_handle.get_webview_window("main") {
                    if let (Some(w), Some(h)) = (saved_width, saved_height) {
                        // 确保大小在合理范围内
                        let w = w.max(800).min(1920);
                        let h = h.max(600).min(1080);
                        let _ = window.set_size(tauri::Size::Logical(tauri::LogicalSize { width: w as f64, height: h as f64 }));
                    }
                }
            }

            // 在后台启动 Python
            tauri::async_runtime::spawn(async move {
                println!("🌟 Yvaine Astra AI 启动中...");

                // 延迟一点再启动，等窗口准备好
                tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;

                match python_manager::start_python_backend().await {
                    Ok(port) => {
                        println!("✅ Python 后端已启动，端口: {}", port);
                        // 通知前端（通过事件）
                        let _ = app_handle.emit("python-started", port);
                    }
                    Err(e) => {
                        eprintln!("❌ Python 后端启动失败: {}", e);
                        let _ = app_handle.emit("python-error", e);
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { .. } = event {
                // 窗口关闭时保存大小（使用逻辑大小）
                let handle = window.app_handle().clone();
                if let Ok(size) = window.inner_size() {
                    // 将物理像素转换为逻辑像素
                    let scale_factor = window.scale_factor().unwrap_or(1.0);
                    let logical_width = (size.width as f64 / scale_factor) as u32;
                    let logical_height = (size.height as f64 / scale_factor) as u32;

                    if let Ok(store) = handle.store("settings.json") {
                        let _ = store.set("window_width", logical_width);
                        let _ = store.set("window_height", logical_height);
                        let _ = store.save();
                        println!("💾 窗口大小已保存: {}x{}", logical_width, logical_height);
                    }
                }

                // 停止 Python
                tauri::async_runtime::spawn(async move {
                    python_manager::stop_python_backend().await;
                });
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}