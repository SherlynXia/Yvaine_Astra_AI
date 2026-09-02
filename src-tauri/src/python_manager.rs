use std::sync::Mutex;
use tokio::process::{Child, Command};
use tokio::io::{BufReader, AsyncBufReadExt};
use tokio::sync::RwLock;

static PYTHON_CHILD: RwLock<Option<Child>> = RwLock::const_new(None);
static PYTHON_PORT: Mutex<u16> = Mutex::new(0);

fn get_project_dir() -> std::path::PathBuf {
    let exe_path = std::env::current_exe().expect("无法获取当前 exe 路径");
    let mut dir = exe_path.parent().unwrap().to_path_buf();

    for _ in 0..5 {
        if dir.join("backend").exists() {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }

    dir = std::env::current_dir().unwrap_or_else(|_| std::path::PathBuf::from("."));
    for _ in 0..3 {
        if dir.join("backend").exists() {
            return dir;
        }
        if !dir.pop() {
            break;
        }
    }

    panic!("无法找到项目根目录（需要包含 backend 目录）");
}

fn find_python() -> std::path::PathBuf {
    let project_dir = get_project_dir();
    let venv_python = project_dir.join("venv").join("Scripts").join("python.exe");
    if venv_python.exists() {
        return venv_python;
    }

    if cfg!(windows) {
        std::path::PathBuf::from("python.exe")
    } else {
        std::path::PathBuf::from("python3")
    }
}

pub async fn start_python_backend() -> Result<u16, String> {
    let port = portpicker::pick_unused_port().ok_or("无法找到可用端口")?;
    *PYTHON_PORT.lock().unwrap() = port;

    let project_dir = get_project_dir();
    let python = find_python();
    let main_py = project_dir.join("backend").join("main.py");

    if !main_py.exists() {
        return Err(format!("找不到 backend/main.py: {:?}", main_py));
    }

    println!("🚀 启动 Python 后端...");
    println!("   Python: {:?}", python);
    println!("   脚本: {:?}", main_py);
    println!("   端口: {}", port);

    let mut child = Command::new(&python)
        .arg("-u")
        .arg(&main_py)
        .env("PYTHON_PORT", port.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .current_dir(&project_dir)
        .stdout(std::process::Stdio::inherit())
        .stderr(std::process::Stdio::inherit())
        .spawn()
        .map_err(|e| format!("启动 Python 失败: {}", e))?;

    // 等待 2 秒，让 Python 有时间启动或崩溃
    tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;

    match child.try_wait() {
        Ok(Some(status)) => {
            return Err(format!(
                "Python 进程意外退出: exit code {:?}",
                status.code()
            ));
        }
        Ok(None) => {
            // 进程还在运行，保存句柄
            let mut guard = PYTHON_CHILD.write().await;
            *guard = Some(child);
            println!("✅ Python 后端已启动，端口: {}", port);
            Ok(port)
        }
        Err(e) => {
            Err(format!("检查 Python 状态失败: {}", e))
        }
    }
}

pub async fn stop_python_backend() {
    let mut guard = PYTHON_CHILD.write().await;
    if let Some(mut child) = guard.take() {
        let _ = child.kill().await;
        println!("🛑 Python 后端已停止");
    }
}

pub async fn is_python_running() -> bool {
    let mut guard = PYTHON_CHILD.write().await;
    if let Some(ref mut child) = *guard {
        match child.try_wait() {
            Ok(None) => true,
            _ => {
                *guard = None;
                false
            }
        }
    } else {
        false
    }
}

pub fn get_python_port() -> u16 {
    *PYTHON_PORT.lock().unwrap()
}