@echo off
REM 关闭命令回显:执行时不在控制台逐条打印命令本身
chcp 65001 >nul
REM 把控制台代码页切换为 UTF-8(65001),使后续 echo 输出支持中文不乱码
setlocal enabledelayedexpansion
REM 启用"延迟环境变量扩展",允许在 for / if 代码块内用 !var! 读到块内刚刚 set 的最新值

set "STEP=INIT"
REM 初始化阶段标识,出错时 :fail 处会打印它来定位
set "ERRMSG="
REM 初始化错误信息变量(空表示无错误)
set "PYTHONUTF8=1"
REM 让后续 Python 子进程启用 UTF-8 模式
set "PYTHONIOENCODING=utf-8"
REM 把 Python 标准 I/O 编码固定为 UTF-8,避免子进程打印中文乱码
if not defined LCA_NONINTERACTIVE set "LCA_NONINTERACTIVE=0"
REM 若外部未指定非交互模式,默认 0(走交互,结束时 pause)
if not defined LCA_INSTALLER_ONLY set "LCA_INSTALLER_ONLY=0"
REM 若外部未指定"仅打包安装程序"模式,默认 0(全量走一遍 Nuitka 构建)

set "SCRIPT_DIR=%~dp0"
REM 取当前 BAT 所在目录(末尾带反斜杠),%~dp0 是 BAT 内置的"驱动器+目录"变量
set "SCRIPT_DIR_NOSLASH=%SCRIPT_DIR:~0,-1%"
REM 用子串切掉末尾的反斜杠,得到没有尾部斜杠的干净路径,方便后续拼接
for %%I in ("%SCRIPT_DIR%..\..") do set "PROJECT_ROOT=%%~fI"
REM 脚本目录向上两级得到工程根目录;%%~fI 把相对路径解析成绝对路径
cd /d "%PROJECT_ROOT%"
REM 切到工程根目录,后续所有相对路径都基于工程根;/d 支持跨盘符切换

echo ========================================
REM 打印外层分隔线
echo   LCA 测试版打包
REM 打印标题
echo ========================================
REM 打印外层分隔线
echo.
REM 打印一个空行

set "STEP=CHECK_VENV"
REM 把阶段标识切到"检查虚拟环境",失败时能精确定位
REM 解析项目内的虚拟环境:优先 .venv,回落到 venv。
REM BAT 直接探测这两个候选,避免在 BAT 中调用 Python 解析(避免 py 启动错版本)。
set "VENV_DIR="
REM 初始化:虚拟环境根目录
set "VENV_SCRIPTS="
REM 初始化:虚拟环境 Scripts 子目录
set "VENV_PYTHON="
REM 初始化:虚拟环境 python.exe 绝对路径
set "VENV_SITE_PACKAGES="
REM 初始化:虚拟环境 site-packages 目录(后续复制 DLL 用)
for %%N in (.venv venv) do (
    REM 遍历两个候选目录名:.venv 优先,venv 兜底
    if not defined VENV_PYTHON (
        REM 仅在尚未确定虚拟环境时才进入探测,避免后写的覆盖前面的
        if exist "%PROJECT_ROOT%\%%N\Scripts\python.exe" (
            REM 候选目录下存在 python.exe,认定这个候选就是虚拟环境
            set "VENV_DIR=%PROJECT_ROOT%\%%N"
            REM 记录虚拟环境根目录
            set "VENV_SCRIPTS=%PROJECT_ROOT%\%%N\Scripts"
            REM 记录 Scripts 子目录
            set "VENV_PYTHON=%PROJECT_ROOT%\%%N\Scripts\python.exe"
            REM 记录 python.exe 的绝对路径,后续 %VENV_PYTHON% 直接调用
            set "VENV_SITE_PACKAGES=%PROJECT_ROOT%\%%N\Lib\site-packages"
            REM 记录 site-packages 目录,后面拷贝原生 DLL 时要用
        )
    )
)

if not defined VENV_PYTHON (
    REM 遍历两个候选后仍未找到可用的虚拟环境
    set "ERRMSG=Missing virtual environment under %PROJECT_ROOT% (expected .venv or venv with Scripts\python.exe)"
    REM 写明期望位置,方便用户自检
    goto fail
    REM 跳到失败处理标签
)
"%VENV_PYTHON%" --version >nul 2>&1
REM 用 --version 自检虚拟环境的 Python 是否真的能跑(>nul 屏蔽输出,2>&1 合并 stderr)
if errorlevel 1 (
    REM 如果 errorlevel >= 1,说明 python.exe 损坏了(典型:pyvenv.cfg 指向的基 Python 被删/换版本)
    set "ERRMSG=Broken python interpreter at %VENV_PYTHON%, please repair the base Python referenced by pyvenv.cfg"
    REM 提示按 pyvenv.cfg 修复基 Python
    goto fail
    REM 跳到失败处理标签
)

set "BUILD_OUTPUT_DIR=%PROJECT_ROOT%\build_assets\packaging\build_output"
REM 定义构建期产物目录(Nuitka 编译/中间缓存都在这下面)
set "RELEASE_OUTPUT_DIR=%PROJECT_ROOT%\build_assets\packaging\release_output"
REM 定义发布产物目录(Inno Setup 生成的安装包最终落到这里)
set "DIST=%BUILD_OUTPUT_DIR%\main.dist"
REM 定义 Nuitka 产物的 dist 子目录(随 main.exe 分发的运行时都在这)
set "BUILD_DIR=%BUILD_OUTPUT_DIR%\main.build"
REM 定义 Nuitka 编译缓存子目录(用于校验打包后的任务模块)

set "STEP=ENSURE_AV_EXCLUSIONS"
REM 阶段切到"确保 Windows Defender 排除项"
echo [0.1/6] Ensure Windows Defender exclusions for packaging...
REM 打印阶段提示,告诉用户正在做的事
%VENV_PYTHON% build_assets\packaging\ensure_packaging_av_exclusions.py --project-root "%PROJECT_ROOT%"
REM 调用脚本,把 build_assets 等目录加进 Defender 白名单,避免被杀软误删/隔离 Nuitka 产物
if errorlevel 1 (
    REM 添加排除项失败(常因权限不足)
    set "ERRMSG=Windows Defender blocked packaging files; add exclusions or rerun as Administrator"
    REM 提示用户加排除项或以管理员身份重试
    goto fail
    REM 跳到失败处理标签
)

if "%LCA_INSTALLER_ONLY%"=="1" goto installer_from_existing
REM 如果外部通过 LCA_INSTALLER_ONLY=1 要求只重打安装包,跳过 Nuitka 全流程,直接进入对应分支

set "STEP=VERIFY_THIRD_PARTY_MANIFEST"
REM 阶段切到"校验三方资源清单"
%VENV_PYTHON% build_assets\packaging\verify_third_party_manifest.py --require-all
REM 调用脚本,核对所有第三方依赖的许可证/正本是否齐全(--require-all 强制要求全部到位)
if errorlevel 1 (
    set "ERRMSG=Third-party manifest verification failed"
    goto fail
)

set "STEP=CLEAN_PREVIOUS_BUILD_ARTIFACTS"
REM 阶段切到"清理旧产物"
echo [0.2/6] Clean previous build traces...
REM 打印阶段提示
if exist "%BUILD_OUTPUT_DIR%" rd /s /q "%BUILD_OUTPUT_DIR%"
REM 强制静默删除旧构建产物目录(/s 含子目录,/q 不询问)
if exist "%RELEASE_OUTPUT_DIR%" rd /s /q "%RELEASE_OUTPUT_DIR%"
REM 强制静默删除旧发布目录(残留的安装包)
if exist "%PROJECT_ROOT%\build_assets\packaging\map_navigation_worker_build_output" rd /s /q "%PROJECT_ROOT%\build_assets\packaging\map_navigation_worker_build_output"
REM 删除 worker 单独构建产生的临时目录
if exist "%PROJECT_ROOT%\build_assets\packaging\_tmp_probe_comtypes.py" del /f /q "%PROJECT_ROOT%\build_assets\packaging\_tmp_probe_comtypes.py" >nul 2>&1
REM 删除探测 comtypes 时产生的临时脚本(/f 强制只读也删,/q 静默,>nul 抑制输出)
if exist "%PROJECT_ROOT%\nuitka-crash-report.xml" del /f /q "%PROJECT_ROOT%\nuitka-crash-report.xml" >nul 2>&1
REM 删除上次 Nuitka 失败时留下的崩溃报告 XML

set "STEP=PREPARE_OUTPUT"
REM 阶段切到"准备输出目录"(实际目录由 Python 端创建)
echo [1/6] Prepare build outputs...
REM 打印阶段提示

set "STEP=BUILD_MAIN_NUITKA"
REM 阶段切到"Nuitka 构建主程序"
echo.
REM 输出一个空行,让控制台更清晰
echo [2/6] Build main.exe with Nuitka...
REM 打印阶段提示
echo.
REM 输出一个空行

%VENV_PYTHON% build_assets\packaging\run_nuitka_main_build.py --project-root "%PROJECT_ROOT%" --output-dir "%BUILD_OUTPUT_DIR%"
REM 调用 Python 脚本,启动 Nuitka 把 main 编译为 main.exe,产物输出到 BUILD_OUTPUT_DIR

if errorlevel 1 (
    REM Nuitka 构建本身失败
    set "ERRMSG=Nuitka main build failed"
    goto fail
)

if not exist "%DIST%\main.exe" (
    REM 即便脚本返回 0,也要兜底检查 main.exe 是否真的生成出来
    set "ERRMSG=Missing %DIST%\main.exe"
    goto fail
)

set "STEP=VERIFY_TASK_MODULES"
REM 阶段切到"校验打包后的任务模块"
echo [2.05/6] Verify packaged task modules...
REM 打印阶段提示
%VENV_PYTHON% build_assets\packaging\verify_packaged_task_modules.py --build-dir "%BUILD_DIR%"
REM 调用脚本,核对 Nuitka 编译产物里的任务模块(.pyc 等)是否完整
if errorlevel 1 (
    set "ERRMSG=Packaged task module verification failed"
    goto fail
)

set "STEP=INJECT_WINDOWS_MANIFEST"
REM 阶段切到"注入 Windows 应用程序清单(manifest)"
echo [2.1/6] Inject Windows DPI manifest...
REM 打印阶段提示:目的是注入 DPI 相关声明,避免高 DPI 屏模糊
%VENV_PYTHON% build_assets\packaging\inject_windows_manifest.py --exe "%DIST%\main.exe" --manifest "%SCRIPT_DIR_NOSLASH%\lca_main.manifest"
REM 调用脚本,把 lca_main.manifest 合入 main.exe 的资源表
if errorlevel 1 (
    set "ERRMSG=Inject Windows DPI manifest failed"
    goto fail
)

REM 离线双身份:清单注入之后再盖编辑器印记(避免被其它资源更新冲掉)
set "STEP=STAMP_EDITOR_ENTRY"
REM 阶段切到"盖编辑器入口印记"
echo [2.15/6] Stamp editor entry identity into main.exe...
REM 打印阶段提示:把"编辑器"入口标识写入 main.exe 的版本信息/资源里
%VENV_PYTHON% -c "from pathlib import Path; from app_core.player.entry_stamp import ENTRY_EDITOR, apply_entry_stamp; p=Path(r'%DIST%\main.exe'); apply_entry_stamp(p, ENTRY_EDITOR); print('entry_stamp=editor path='+str(p))"
REM 用 python -c 直接调用项目内的入口印记工具,把 ENTRY_EDITOR 这个常量写入 main.exe
if errorlevel 1 (
    set "ERRMSG=Stamp editor entry identity failed"
    goto fail
)

set "STEP=CHECK_CORE_RESOURCES"
REM 阶段切到"检查核心依赖资源"(原生 DLL、AHK 套件等)
echo [2.5/6] Check required resources...
REM 打印阶段提示

if not exist "%VENV_SITE_PACKAGES%\uiautomation\bin\UIAutomationClient_VC140_X64.dll" (
    REM 检查虚拟环境里是否有 x64 版 UIAutomation 原生 DLL(Windows UI 自动化要用)
    set "ERRMSG=Missing source UIAutomationClient_VC140_X64.dll"
    goto fail
)
if not exist "%VENV_SITE_PACKAGES%\uiautomation\bin\UIAutomationClient_VC140_X86.dll" (
    REM 同上,检查 x86 版
    set "ERRMSG=Missing source UIAutomationClient_VC140_X86.dll"
    goto fail
)
if not exist "%DIST%\uiautomation\bin" mkdir "%DIST%\uiautomation\bin"
REM 在 dist 中按原结构创建 uiautomation/bin 子目录
for %%f in (UIAutomationClient_VC140_X64.dll UIAutomationClient_VC140_X86.dll) do (
    REM 遍历两个架构的 DLL
    copy /y "%VENV_SITE_PACKAGES%\uiautomation\bin\%%f" "%DIST%\uiautomation\bin\%%f" >nul 2>&1
    REM /y 强制覆盖,把 DLL 从虚拟环境拷到 dist
    if not exist "%DIST%\uiautomation\bin\%%f" (
        REM 复制后再校验一次,确保目标确实存在
        set "ERRMSG=Missing UIAutomation runtime DLL: %%f"
        goto fail
    )
)

if not exist "%DIST%\Interception\library\x64\interception.dll" (
    REM dist 里没有 x64 Interception DLL(键盘拦截驱动)
    if not exist "Interception\library\x64\interception.dll" (
        REM 那就到工程根目录下的 Interception 源目录去找
        set "ERRMSG=Missing source Interception x64 DLL"
        goto fail
    )
    if not exist "%DIST%\Interception\library\x64" mkdir "%DIST%\Interception\library\x64"
    REM dist 里没有对应目录则创建
copy "Interception\library\x64\interception.dll" "%DIST%\Interception\library\x64\interception.dll" >nul 2>&1
    REM 把源 DLL 拷进 dist(注意这里少了 if 包裹的一行缩进,沿用原行为准,行为上仍正确)
)
if not exist "%DIST%\Interception\library\x64\interception.dll" (
    REM 兜底再校验一次 x64 DLL 是否就位
    set "ERRMSG=Missing Interception x64 DLL"
    goto fail
)

if not exist "%DIST%\Interception\library\x86\interception.dll" (
    REM 同上,处理 x86 版 Interception DLL
    if not exist "Interception\library\x86\interception.dll" (
        set "ERRMSG=Missing source Interception x86 DLL"
        goto fail
    )
    if not exist "%DIST%\Interception\library\x86" mkdir "%DIST%\Interception\library\x86"
    copy "Interception\library\x86\interception.dll" "%DIST%\Interception\library\x86\interception.dll" >nul 2>&1
)
if not exist "%DIST%\Interception\library\x86\interception.dll" (
    set "ERRMSG=Missing Interception x86 DLL"
    goto fail
)
REM 以下四个文件由 run_nuitka_main_build.py 的 DATA_FILE_SPECS 打进 dist,
REM 这里只校验产物,不再第二次拷贝,避免两份清单各改各的。
for %%f in (
    REM 遍历要校验的"应该已经由 Nuitka DATA_FILE_SPECS 注入 dist 的"文件
    "tools\ibinputsimulator\ib_worker_core.ahk"
    REM AHK 内核脚本,worker 主体逻辑
    "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.ahk"
    REM AHK2 入口脚本(绑定层)
    "tools\ibinputsimulator\Binding.AHK2\IbInputSimulator.dll"
    REM AHK2 提供的输入模拟原生 DLL
    "AutoHotkey\AutoHotkey64.exe"
    REM 64 位 AutoHotkey 可执行,被 worker 拉起
) do (
    if not exist "%DIST%\%%~f" (
        REM %%~f 去引号,校验这个相对路径文件是否真的被 Nuitka 打进 dist
        set "ERRMSG=Nuitka data file missing from dist: %%~f (check DATA_FILE_SPECS)"
        goto fail
    )
)
findstr /l /c:"UIntP" "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" >nul
REM /l 字面匹配,/c 指定要查找的字符串;在新版 AHK 脚本中应有 UIntP 类型
if errorlevel 1 (
    REM 找不到 UIntP 说明脚本不是新版
    set "ERRMSG=ib_worker_core.ahk version check failed (UIntP missing)"
    goto fail
)
findstr /l /c:"UInt*" "%DIST%\tools\ibinputsimulator\ib_worker_core.ahk" >nul
REM 再搜一次旧版标记 UInt*,用来确认旧版语法已被彻底替换
if not errorlevel 1 (
    REM 找到了说明还残留旧版,必须失败
    set "ERRMSG=ib_worker_core.ahk version check failed (legacy UInt* found)"
    goto fail
)
set "STEP=COPY_VC_RUNTIME"
REM 阶段切到"拷贝 VC 运行库"
echo [3/6] Copy VC runtime...
REM 打印阶段提示
set "VCRUNTIME=C:\Windows\System32"
REM 把系统 System32 当作 VC++ 运行库的来源(标准做法)
if not exist "%DIST%\AutoHotkey" mkdir "%DIST%\AutoHotkey"
REM 为 AutoHotkey64.exe 创建同目录,准备把 VC DLL 放在它旁边便于加载
if not exist "%DIST%\tools\ibinputsimulator\Binding.AHK2" mkdir "%DIST%\tools\ibinputsimulator\Binding.AHK2"
REM 同上,为 AHK2 绑定目录创建子目录
for %%f in (concrt140.dll msvcp140.dll vcomp140.dll vcruntime140.dll vcruntime140_1.dll) do (
    REM 遍历 5 个常用的 VC++ 运行库 DLL
    if exist "%VCRUNTIME%\%%f" (
        REM 仅当系统目录里确实有这个 DLL 时才拷,缺哪个就跳过哪个不报错
        copy "%VCRUNTIME%\%%f" "%DIST%\%%f" >nul 2>&1
        REM 拷贝到 dist 根目录,>nul 2>&1 抑制屏幕输出与错误
        copy "%VCRUNTIME%\%%f" "%DIST%\AutoHotkey\%%f" >nul 2>&1
        REM 拷贝到 AutoHotkey 子目录,给 AutoHotkey64.exe 用
        copy "%VCRUNTIME%\%%f" "%DIST%\tools\ibinputsimulator\Binding.AHK2\%%f" >nul 2>&1
        REM 拷贝到 AHK2 绑定目录,给 IbInputSimulator.dll 用
    )
)
for %%f in (msvcp140.dll vcruntime140.dll vcruntime140_1.dll) do (
    REM 这三个是最关键的 VC DLL,必须校验最终在 dist 根目录中存在
    if not exist "%DIST%\%%f" (
        set "ERRMSG=Missing VC runtime DLL: %%f"
        goto fail
    )
)

set "STEP=STAGE_PACKAGED_RUNTIME_ASSETS"
REM 阶段切到"放置打包运行时资源"
%VENV_PYTHON% build_assets\packaging\stage_packaged_runtime_assets.py --project-root "%PROJECT_ROOT%" --dist "%DIST%"
REM 调用脚本,把 OCR 模型、字典、其它第三方运行时等拷贝到 dist
if errorlevel 1 (
    set "ERRMSG=Stage packaged runtime assets failed"
    goto fail
)

set "STEP=VERIFY_PACKAGED_OCR_RUNTIME"
REM 阶段切到"校验离线 OCR 运行时"
echo [5.7/6] Verify offline PP-OCRv4 runtime...
REM 打印阶段提示,说明在核对 PP-OCRv4 离线包
%VENV_PYTHON% build_assets\packaging\verify_packaged_ocr_runtime.py --dist "%DIST%"
REM 调用脚本,确保 OCR 模型/字典/推理库齐全且能被加载
if errorlevel 1 (
    set "ERRMSG=Packaged OCR runtime verification failed"
    goto fail
)

set "STEP=VERIFY_NO_SOURCE_FILES"
REM 阶段切到"校验无源码泄露"
%VENV_PYTHON% build_assets\packaging\verify_no_source_files.py --dist "%DIST%"
REM 调用脚本,扫描 dist 中是否残留 .py 源文件(防止源码外泄)
if errorlevel 1 (
    set "ERRMSG=Packaged dist still contains Python source files"
    goto fail
)

set "STEP=CHECK_SUBPROCESS_RUNTIME"
REM 阶段切到"子进程 worker 烟测"
echo [5.8/6] Smoke test final packaged subprocess workers...
REM 打印阶段提示
%VENV_PYTHON% build_assets\packaging\verify_packaged_subprocess_workers.py --exe "%DIST%\main.exe" --build-dir "%BUILD_DIR%"
REM 用打包后的 main.exe 实际拉起 worker 子进程做冒烟测试,确保运行时可用
if errorlevel 1 (
    set "ERRMSG=Packaged subprocess workers smoke test failed"
    goto fail
)

set "STEP=WRITE_BUILD_METADATA"
REM 阶段切到"写入构建元数据"
%VENV_PYTHON% build_assets\packaging\write_build_metadata.py --dist "%DIST%"
REM 调用脚本,把构建时间、版本号、Git SHA 等写入 dist 的 build_info.json
if errorlevel 1 (
    set "ERRMSG=Build metadata generation failed"
    goto fail
)
%VENV_PYTHON% build_assets\packaging\generate_sbom.py --output "%DIST%\sbom.cdx.json"
REM 调用脚本生成 SBOM(软件物料清单,符合 CycloneDX 规范),供合规/审计使用
if errorlevel 1 (
    set "ERRMSG=SBOM generation failed"
    goto fail
)

echo.
echo ========================================
echo   Build stage completed
REM 提示构建阶段已完成
echo   Output dir: %DIST%
REM 提示产物所在目录
echo ========================================
echo.

for /f "tokens=1" %%a in ('powershell -command "(Get-ChildItem '%DIST%' -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB" 2^>nul') do set SIZE=%%a
REM 调用 PowerShell 递归统计 dist 大小并除以 1MB 换算成 MB;^> 是 BAT 里 > 的转义,2>nul 屏蔽错误
if defined SIZE (
    REM PowerShell 成功取到 SIZE 时
    echo Total size: ~ %SIZE% MB
    REM 输出大约多少 MB
) else (
    REM 取不到则兜底
    dir /s "%DIST%"
    REM 用 dir /s 列出所有文件作为兜底展示
)

set "STEP=CHECK_INNO_SETUP"
REM 阶段切到"探测 Inno Setup"
goto build_installers
REM 跳过 installer_from_existing 分支(全量构建走这里),直接进入安装包构建

:installer_from_existing
REM "仅打包安装程序"模式的入口标签(由 63 行的 goto 跳转过来)
echo.
echo ========================================
echo   Installer-only mode
REM 提示当前是"仅打包安装程序"模式
echo ========================================
echo.
if not exist "%DIST%\main.exe" (
    REM 这种模式要求 dist 里已经有上次构建好的 main.exe
    set "ERRMSG=Installer-only mode requires existing %DIST%\main.exe"
    goto fail
)
set "STEP=STAGE_PACKAGED_RUNTIME_ASSETS"
REM 复用同样的阶段名,再放一次运行时资源(以防资源被改动过)
%VENV_PYTHON% build_assets\packaging\stage_packaged_runtime_assets.py --project-root "%PROJECT_ROOT%" --dist "%DIST%"
REM 重新放置运行时资源
if errorlevel 1 (
    set "ERRMSG=Stage packaged runtime assets failed"
    goto fail
)

:build_installers
REM 安装包构建阶段入口标签(由 269 行 goto 跳转过来,或从 installer_from_existing 自然落入)
echo.
echo ========================================
echo   Build installers
REM 提示接下来开始构建安装包
echo ========================================
echo.

set "ISCC="
REM 初始化 ISCC.exe(Inno Setup 编译器)的路径变量为空
for %%p in (
    REM 遍历常见 Inno Setup 安装位置
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
    REM 候选 1:32 位 Program Files
    "C:\Program Files\Inno Setup 6\ISCC.exe"
    REM 候选 2:64 位 Program Files
    "D:\Inno Setup 6\ISCC.exe"
    REM 候选 3:D 盘直装
    "D:\app\Scoop\apps\inno-setup\current\ISCC.exe"
    REM 候选 4:Scoop 包管理器安装路径
) do if exist %%p set "ISCC=%%~p"
REM 第一个真实存在的路径赋给 ISCC,%%~p 用于去引号

if "%ISCC%"=="" (
    REM 四个候选都没找到 ISCC.exe
    echo Inno Setup not found, skip installer build.
    REM 提示跳过安装包构建
    echo Please install Inno Setup locally and retry.
    REM 提示安装后再试
    echo.
    if not "%LCA_NONINTERACTIVE%"=="1" pause
    REM 交互模式下暂停,让用户看到提示
    exit /b 0
    REM 用错误码 0 退出,表示整体构建成功,只是没生成安装包
)

set "STEP=VERIFY_STAGED_PLUGIN_RUNTIME"
REM 阶段切到"校验待打包的插件运行时"
%VENV_PYTHON% build_assets\packaging\ensure_packaging_av_exclusions.py --project-root "%PROJECT_ROOT%" --verify-dist "%DIST%" --skip-add
REM 复用同一个脚本,这次只校验 dist 中所有资源是否被 Defender 隔离(--skip-add 表示不再追加排除项)
if errorlevel 1 (
    set "ERRMSG=Staged plugin runtime missing or quarantined before Inno Setup"
    goto fail
)

set "STEP=BUILD_MAIN_INSTALLER"
REM 阶段切到"构建主安装包"
echo Build main installer...
REM 打印阶段提示
if "%LCA_NONINTERACTIVE%"=="1" (
    REM 非交互模式:把 /DNonInteractive=1 传给 ISCC,避免脚本在编译期弹窗
    "%ISCC%" /DNonInteractive=1 "%SCRIPT_DIR_NOSLASH%\setup.iss"
    REM 调用 ISCC 编译 setup.iss 生成安装包
) else (
    REM 交互模式直接编译
    "%ISCC%" "%SCRIPT_DIR_NOSLASH%\setup.iss"
    REM 调用 ISCC 编译 setup.iss 生成安装包
)
if errorlevel 1 (
    set "ERRMSG=Main installer build failed"
    goto fail
)

echo.
echo ========================================
echo   Build complete
REM 提示构建已全部完成
echo   Installer: build_assets\packaging\release_output\LCA_测试版_Setup.exe
REM 告诉用户安装包最终落点
echo ========================================
echo.
if not "%LCA_NONINTERACTIVE%"=="1" pause
REM 交互模式暂停,让用户看清最终路径
exit /b 0
REM 以错误码 0 退出,表示整体成功

:fail
REM 失败处理入口标签:任意 goto fail 都会跳到这里
echo.
echo ========================================
echo   BUILD FAILED
REM 大字提示构建失败
echo ========================================
echo Step: %STEP%
REM 打印失败发生在哪个阶段,便于排查
if defined ERRMSG echo Error: %ERRMSG%
REM 如果有具体错误信息则一并打印
echo ErrorLevel: %errorlevel%
REM 打印上一个命令的错误码
echo.
if not "%LCA_NONINTERACTIVE%"=="1" pause
REM 交互模式暂停,便于查看失败原因
exit /b 1
REM 以错误码 1 退出,表示构建失败


