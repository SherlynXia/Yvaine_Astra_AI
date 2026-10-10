use std::sync::Mutex;
use std::path::PathBuf;
use tokio::process::{Child, Command};
use tokio::sync::RwLock;
use tokio::net::TcpStream;
use tokio::time::{sleep, Duration, Instant};

static PYTHON_CHILD: RwLock<Option<Child>> = RwLock::const_new(None);
static PYTHON_PORT: Mutex<u16> = Mutex::new(0);

/// 定位项目根目录（包含 backend/ 的目录）
fn get_project_dir() -> Option<PathBuf> {
    // 1. 优先用环境变量（开发期最可靠）
    if let Ok(dir) = std::env::var("YVAINE_PROJECT_DIR") {
        let p = PathBuf::from(dir);
        if p.join("backend").exists() {
            return Some(p);
        }
    }

    // 2. 从 current_dir 往上找
    if let Ok(cwd) = std::env::current_dir() {
        let mut dir = cwd;
        for _ in 0..5 {
            if dir.join("backend").exists() && dir.join("src-tauri").exists() {
                return Some(dir);
            }
            if !dir.pop() { break; }
        }
    }

    // 3. 从 exe 位置往上找（打包后不适用，留作兜底）
    if let Ok(exe) = std::env::current_exe() {
        let mut dir = exe.parent()?.to_path_buf();
        for _ in 0..5 {
            if dir.join("backend").exists() {
                return Some(dir);
            }
            if !dir.pop() { break; }
        }
    }

    None
}

/// 找到 Python 可执行文件
fn find_python(project_dir: &PathBuf) -> PathBuf {
    // 1. 虚拟环境优先
    let venv_python = project_dir.join("venv").join("Scripts").join("python.exe");
    if venv_python.exists() {
        return venv_python;
    }
    let venv_python_unix = project_dir.join("venv").join("bin").join("python");
    if venv_python_unix.exists() {
        return venv_python_unix;
    }

    // 2. 兜底
    if cfg!(windows) {
        PathBuf::from("python.exe")
    } else {
        PathBuf::from("python3")
    }
}

/// 等待端口真正可连接（比"进程存活"更可靠）
async fn wait_for_port(port: u16, timeout: Duration) -> bool {
    let deadline = Instant::now() + timeout;
    while Instant::now() < deadline {
        if TcpStream::connect(("127.0.0.1", port)).await.is_ok() {
            return true;
        }
        sleep(Duration::from_millis(200)).await;
    }
    false
}

pub async fn start_python_backend() -> Result<u16, String> {
    let project_dir = get_project_dir()
        .ok_or_else(|| "无法找到项目根目录（需要包含 backend/ 目录）".to_string())?;

    let python = find_python(&project_dir);
    let main_py = project_dir.join("backend").join("main.py");

    if !main_py.exists() {
        return Err(format!("找不到 backend/main.py: {:?}", main_py));
    }

    let port = portpicker::pick_unused_port().ok_or("无法找到可用端口")?;
    *PYTHON_PORT.lock().unwrap() = port;

    println!("🚀 启动 Python 后端...");
    println!("   项目根: {:?}", project_dir);
    println!("   Python: {:?}", python);
    println!("   脚本:   {:?}", main_py);
    println!("   端口:   {}", port);

    // 用 piped 捕获 stdout/stderr，这样启动失败能看到原因
    let mut child = Command::new(&python)
        .arg("-u")
        .arg(&main_py)
        .env("PYTHON_PORT", port.to_string())
        .env("PYTHONUNBUFFERED", "1")
        .env("PYTHONIOENCODING", "utf-8")
        .current_dir(&project_dir)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("启动 Python 失败: {}", e))?;

    // 异步读取 stderr，出错时能看到完整信息
    let stderr = child.stderr.take();
    let stdout = child.stdout.take();
    if let Some(stderr) = stderr {
        tokio::spawn(async move {
            use tokio::io::{AsyncBufReadExt, BufReader};
            let mut reader = BufReader::new(stderr).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                eprintln!("[Python ERR] {}", line);
            }
        });
    }
    if let Some(stdout) = stdout {
        tokio::spawn(async move {
            use tokio::io::{AsyncBufReadExt, BufReader};
            let mut reader = BufReader::new(stdout).lines();
            while let Ok(Some(line)) = reader.next_line().await {
                println!("[Python] {}", line);
            }
        });
    }

    // 🔑 关键：等端口真正可连接，最多 30 秒
    let ready = wait_for_port(port, Duration::from_secs(30)).await;

    if !ready {
        // 端口没起来，检查进程是否还活着
        match child.try_wait() {
            Ok(Some(status)) => {
                return Err(format!(
                    "Python 进程意外退出: exit code {:?}",
                    status.code()
                ));
            }
            Ok(None) => {
                // 进程还活着但端口没开，可能是 uvicorn 崩了但 python 没退
                let _ = child.kill().await;
                return Err(format!(
                    "Python 启动超时（30秒内端口 {} 未就绪）",
                    port
                ));
            }
            Err(e) => {
                return Err(format!("检查 Python 状态失败: {}", e));
            }
        }
    }

    let mut guard = PYTHON_CHILD.write().await;
    *guard = Some(child);
    println!("✅ Python 后端已就绪，端口: {}", port);
    Ok(port)
}

pub async fn stop_python_backend() {
    let mut guard = PYTHON_CHILD.write().await;
    if let Some(mut child) = guard.take() {
        let pid = child.id();
        println!("🛑 正在停止 Python 后端 (PID: {:?})...", pid);

        // 先优雅关闭
        let _ = child.kill().await;

        // 🔑 关键：Windows 上用 taskkill /T 杀整个进程树
        #[cfg(windows)]
        if let Some(pid) = pid {
            let _ = tokio::process::Command::new("taskkill")
                .args(["/F", "/T", "/PID", &pid.to_string()])
                .output()
                .await;
        }

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