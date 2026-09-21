#define COBJMACROS
#include <winsock2.h>
#include <windows.h>
#include <shellapi.h>
#include <shlobj.h>
#include <objbase.h>
#include <iphlpapi.h>
#include <tlhelp32.h>
#include <wchar.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#ifndef AF_INET
#define AF_INET 2
#endif
#ifndef TCP_TABLE_OWNER_PID_LISTENER
#define TCP_TABLE_OWNER_PID_LISTENER 3
#endif

#ifndef CREATE_BREAKAWAY_FROM_JOB
#define CREATE_BREAKAWAY_FROM_JOB 0x01000000
#endif
#define PORT 18765
#define MAXP 1024
#define TITLE L"电子电器智能体"
#define SHORTCUT_LABEL L"电子电器智能体"
#define SHORTCUT_NAME L"电子电器智能体.lnk"
#define SHORTCUT_NAME_OLD L"电子电器SOR填表.lnk"
#define ZIP_MAGIC "EKROWZP1"
#define ZIP_MAGIC_LEN 8

static int file_exists(const wchar_t *path)
{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY);
}

static int dir_exists(const wchar_t *path)
{
    DWORD attr = GetFileAttributesW(path);
    return attr != INVALID_FILE_ATTRIBUTES && (attr & FILE_ATTRIBUTE_DIRECTORY);
}

static void dirname_of(wchar_t *out, size_t n, const wchar_t *path)
{
    wcsncpy(out, path, n - 1);
    out[n - 1] = 0;
    wchar_t *slash = wcsrchr(out, L'\\');
    if (slash)
        *slash = 0;
}

static void join2(wchar_t *out, size_t n, const wchar_t *a, const wchar_t *b)
{
    size_t la = wcslen(a);
    if (la > 0 && a[la - 1] == L'\\')
        _snwprintf(out, n, L"%s%s", a, b);
    else
        _snwprintf(out, n, L"%s\\%s", a, b);
    out[n - 1] = 0;
}

static unsigned short port_host(DWORD net_port)
{
    unsigned short p = (unsigned short)net_port;
    return (unsigned short)((p >> 8) | (p << 8));
}

static int wsa_ready(void)
{
    static int started = 0;
    static int ok = 0;
    WSADATA data;
    if (!started) {
        started = 1;
        ok = (WSAStartup(MAKEWORD(2, 2), &data) == 0);
    }
    return ok;
}

static void pump_ui(void)
{
    MSG msg;
    while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
}

static int port_accepts(void)
{
    SOCKET s;
    struct sockaddr_in addr;
    DWORD ms = 150;
    if (!wsa_ready())
        return 0;
    s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (s == INVALID_SOCKET)
        return 0;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (const char *)&ms, sizeof(ms));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (const char *)&ms, sizeof(ms));
    memset(&addr, 0, sizeof(addr));
    addr.sin_family = AF_INET;
    addr.sin_port = htons(PORT);
    addr.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    if (connect(s, (struct sockaddr *)&addr, sizeof(addr)) == 0) {
        closesocket(s);
        return 1;
    }
    closesocket(s);
    return 0;
}

static DWORD find_listener_pid(void)
{
    DWORD bytes = 0;
    DWORD pid = 0;
    int attempt;
    GetExtendedTcpTable(NULL, &bytes, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0);
    if (bytes == 0)
        bytes = 4096;
    for (attempt = 0; attempt < 4 && !pid; attempt++) {
        char *buf;
        DWORD need = bytes + 512;
        DWORD err;
        buf = (char *)malloc(need);
        if (!buf)
            return 0;
        bytes = need;
        err = GetExtendedTcpTable(buf, &bytes, FALSE, AF_INET, TCP_TABLE_OWNER_PID_LISTENER, 0);
        if (err == NO_ERROR) {
            MIB_TCPTABLE_OWNER_PID *table = (MIB_TCPTABLE_OWNER_PID *)buf;
            DWORD i;
            for (i = 0; i < table->dwNumEntries; i++) {
                if (port_host(table->table[i].dwLocalPort) == PORT) {
                    pid = table->table[i].dwOwningPid;
                    break;
                }
            }
        }
        free(buf);
        if (err == NO_ERROR)
            break;
    }
    return pid;
}

static int service_up(void)
{
    return port_accepts() || find_listener_pid() != 0;
}

static void kill_pid(DWORD pid)
{
    HANDLE proc;
    if (!pid)
        return;
    proc = OpenProcess(PROCESS_TERMINATE, FALSE, pid);
    if (!proc)
        return;
    TerminateProcess(proc, 0);
    CloseHandle(proc);
}

static int path_is_under(const wchar_t *file, const wchar_t *root)
{
    wchar_t a[MAXP], b[MAXP];
    size_t nb;
    wcsncpy(a, file, MAXP - 1);
    a[MAXP - 1] = 0;
    wcsncpy(b, root, MAXP - 1);
    b[MAXP - 1] = 0;
    CharUpperW(a);
    CharUpperW(b);
    nb = wcslen(b);
    while (nb > 0 && b[nb - 1] == L'\\')
        b[--nb] = 0;
    if (nb == 0 || wcsncmp(a, b, nb) != 0)
        return 0;
    return a[nb] == 0 || a[nb] == L'\\';
}

static void stop_dir_processes(const wchar_t *dest)
{
    HANDLE snap;
    PROCESSENTRY32W pe;
    DWORD self = GetCurrentProcessId();

    kill_pid(find_listener_pid());
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE)
        return;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            HANDLE proc;
            wchar_t image[MAXP];
            DWORD n = MAXP;
            if (pe.th32ProcessID == self)
                continue;
            proc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION | PROCESS_TERMINATE, FALSE, pe.th32ProcessID);
            if (!proc)
                continue;
            if (QueryFullProcessImageNameW(proc, 0, image, &n) && path_is_under(image, dest))
                TerminateProcess(proc, 0);
            CloseHandle(proc);
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    pump_ui();
    Sleep(400);
}

static int stop_listener(void)
{
    DWORD pid = find_listener_pid();
    if (!pid) {
        MessageBoxW(NULL, L"当前没有在运行。", TITLE, MB_OK | MB_ICONINFORMATION);
        return 0;
    }
    kill_pid(pid);
    MessageBoxW(NULL, L"已停止出表服务。", TITLE, MB_OK | MB_ICONINFORMATION);
    return 0;
}

static int run_hidden_wait(wchar_t *cmdline, const wchar_t *cwd, int hide, int wait, HANDLE log)
{
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD flags = 0;
    DWORD code = 1;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = hide ? SW_HIDE : SW_SHOWNORMAL;
    if (hide)
        flags |= CREATE_NO_WINDOW;
    if (log) {
        si.dwFlags |= STARTF_USESTDHANDLES;
        si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);
        si.hStdOutput = log;
        si.hStdError = log;
    }
    if (!CreateProcessW(NULL, cmdline, NULL, NULL, log ? TRUE : FALSE, flags, NULL, cwd, &si, &pi))
        return 1;
    if (wait) {
        while (WaitForSingleObject(pi.hProcess, 200) == WAIT_TIMEOUT)
            pump_ui();
        if (!GetExitCodeProcess(pi.hProcess, &code))
            code = 1;
    } else {
        code = 0;
    }
    CloseHandle(pi.hProcess);
    CloseHandle(pi.hThread);
    return code == 0 ? 0 : 1;
}

static HWND g_status = NULL;
static HWND g_status_text = NULL;

static void status_close(void)
{
    if (g_status) {
        DestroyWindow(g_status);
        g_status = NULL;
        g_status_text = NULL;
        pump_ui();
    }
}

static void status_show(const wchar_t *text)
{
    if (!g_status) {
        WNDCLASSW wc;
        HFONT font;
        ZeroMemory(&wc, sizeof(wc));
        wc.lpfnWndProc = DefWindowProcW;
        wc.hInstance = GetModuleHandleW(NULL);
        wc.hCursor = LoadCursorW(NULL, IDC_WAIT);
        wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
        wc.lpszClassName = L"ElectricalKrowStatus";
        RegisterClassW(&wc);
        g_status = CreateWindowExW(
            WS_EX_TOPMOST | WS_EX_APPWINDOW,
            L"ElectricalKrowStatus",
            SHORTCUT_LABEL,
            WS_OVERLAPPED | WS_CAPTION | WS_VISIBLE,
            CW_USEDEFAULT,
            CW_USEDEFAULT,
            460,
            150,
            NULL,
            NULL,
            GetModuleHandleW(NULL),
            NULL);
        if (!g_status)
            return;
        g_status_text = CreateWindowW(
            L"STATIC",
            text,
            WS_CHILD | WS_VISIBLE | SS_LEFT,
            20,
            24,
            410,
            70,
            g_status,
            NULL,
            GetModuleHandleW(NULL),
            NULL);
        font = (HFONT)GetStockObject(DEFAULT_GUI_FONT);
        if (g_status_text && font)
            SendMessageW(g_status_text, WM_SETFONT, (WPARAM)font, TRUE);
    } else if (g_status_text) {
        SetWindowTextW(g_status_text, text);
    }
    if (g_status) {
        ShowWindow(g_status, SW_SHOWNORMAL);
        SetForegroundWindow(g_status);
    }
    pump_ui();
}

static HANDLE start_gui(wchar_t *cmdline, const wchar_t *cwd)
{
    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    DWORD flags = CREATE_BREAKAWAY_FROM_JOB | CREATE_NEW_PROCESS_GROUP;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_SHOWNORMAL;
    if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, flags, NULL, cwd, &si, &pi)) {
        if (!CreateProcessW(NULL, cmdline, NULL, NULL, FALSE, CREATE_NEW_PROCESS_GROUP, NULL, cwd, &si, &pi))
            return NULL;
    }
    AllowSetForegroundWindow(pi.dwProcessId);
    CloseHandle(pi.hThread);
    return pi.hProcess;
}

/* 0=已在听端口  1=进程已退出  2=仍在启动 */
static int wait_ready(HANDLE proc, int ms)
{
    DWORD t0 = GetTickCount();
    while ((GetTickCount() - t0) < (DWORD)ms) {
        if (service_up())
            return 0;
        if (proc && WaitForSingleObject(proc, 0) == WAIT_OBJECT_0)
            return 1;
        pump_ui();
        Sleep(200);
    }
    if (service_up())
        return 0;
    if (proc && WaitForSingleObject(proc, 0) == WAIT_OBJECT_0)
        return 1;
    return 2;
}

static int start_from_dir(const wchar_t *dir)
{
    wchar_t marker[MAXP], pyw[MAXP], runpy[MAXP], bat[MAXP], cmd[MAXP * 2];
    join2(marker, MAXP, dir, L"python\\.deps-ok");
    join2(pyw, MAXP, dir, L"python\\pythonw.exe");
    join2(runpy, MAXP, dir, L"run.py");
    join2(bat, MAXP, dir, L"start.bat");
    if (!file_exists(runpy) || !file_exists(pyw)) {
        status_close();
        MessageBoxW(NULL, L"程序文件不完整。请重新安装或解压完整压缩包。", TITLE, MB_OK | MB_ICONERROR);
        return 1;
    }
    {
        wchar_t httpx[MAXP];
        join2(httpx, MAXP, dir, L"python\\Lib\\site-packages\\httpx\\__init__.py");
        if (!file_exists(httpx)) {
            status_close();
            MessageBoxW(
                NULL,
                L"安装不完整，缺少依赖 httpx。\n\n"
                L"请先关掉出表窗口，删掉文件夹：\n"
                L"%LOCALAPPDATA%\\electrical-krow-app\n"
                L"再用新的 exe 安装，不要用旧目录。",
                TITLE,
                MB_OK | MB_ICONERROR);
            return 1;
        }
    }
    if (!file_exists(marker)) {
        if (!file_exists(bat)) {
            status_close();
            MessageBoxW(NULL, L"找不到 start.bat。", TITLE, MB_OK | MB_ICONERROR);
            return 1;
        }
        _snwprintf(cmd, MAXP * 2, L"cmd.exe /c \"%s\"", bat);
        cmd[MAXP * 2 - 1] = 0;
        return run_hidden_wait(cmd, dir, 0, 1, NULL);
    }
    status_show(L"正在打开电子电器智能体，请稍候…");
    _snwprintf(cmd, MAXP * 2, L"\"%s\" \"%s\"", pyw, runpy);
    cmd[MAXP * 2 - 1] = 0;
    {
        HANDLE proc = start_gui(cmd, dir);
        int ready;
        if (!proc) {
            status_close();
            MessageBoxW(NULL, L"无法打开电子电器智能体。", TITLE, MB_OK | MB_ICONERROR);
            return 1;
        }
        /* 现场杀毒会扫几千个 py 文件，第一次启动经常超过 45 秒。 */
        ready = wait_ready(proc, 120000);
        CloseHandle(proc);
        status_close();
        if (ready == 0)
            return 0;
        if (ready == 2)
            return 0;
        MessageBoxW(
            NULL,
            L"安装已完成，但没有打开电子电器智能体。\n\n"
            L"请双击桌面快捷方式「电子电器智能体」。\n"
            L"若仍没有窗口，双击安装目录里的 console.bat 查看报错，\n"
            L"并把窗口里的文字发给我们。\n"
            L"日志在 %LOCALAPPDATA%\\electrical-krow\\gateway.log",
            TITLE,
            MB_OK | MB_ICONWARNING);
        return 1;
    }
}

static void append_log(const wchar_t *log_path, const char *text)
{
    HANDLE h = CreateFileW(
        log_path,
        FILE_APPEND_DATA,
        FILE_SHARE_READ,
        NULL,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    DWORD wr = 0;
    if (h == INVALID_HANDLE_VALUE)
        return;
    WriteFile(h, text, (DWORD)strlen(text), &wr, NULL);
    WriteFile(h, "\r\n", 2, &wr, NULL);
    CloseHandle(h);
}

static void append_logw(const wchar_t *log_path, const wchar_t *text)
{
    char utf8[4096];
    int n = WideCharToMultiByte(CP_UTF8, 0, text, -1, utf8, (int)sizeof(utf8) - 1, NULL, NULL);
    if (n <= 0)
        return;
    utf8[n - 1] = 0;
    append_log(log_path, utf8);
}

static int fail_install(const wchar_t *log_path, const wchar_t *reason)
{
    status_close();
    append_logw(log_path, reason);
    wchar_t msg[1600];
    _snwprintf(
        msg,
        1600,
        L"%s\n\n详细日志：\n%s\n\n可以改用 zip：解压后双击「启动SOR填表.exe」。\n"
        L"若杀毒软件拦截，请把安装包和 %%LOCALAPPDATA%%\\electrical-krow-app 加白名单后重试。",
        reason,
        log_path);
    msg[1599] = 0;
    MessageBoxW(NULL, msg, TITLE, MB_OK | MB_ICONERROR);
    return 1;
}

static ULONGLONG file_size_of(const wchar_t *path)
{
    HANDLE h = CreateFileW(
        path,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    LARGE_INTEGER sz;
    if (h == INVALID_HANDLE_VALUE)
        return 0;
    if (!GetFileSizeEx(h, &sz)) {
        CloseHandle(h);
        return 0;
    }
    CloseHandle(h);
    return (ULONGLONG)sz.QuadPart;
}

static int copy_range(const wchar_t *src, ULONGLONG off, ULONGLONG len, const wchar_t *dst)
{
    HANDLE in;
    HANDLE out;
    LARGE_INTEGER pos;
    char buf[65536];

    in = CreateFileW(
        src,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    if (in == INVALID_HANDLE_VALUE)
        return 1;
    out = CreateFileW(dst, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (out == INVALID_HANDLE_VALUE) {
        CloseHandle(in);
        return 1;
    }
    pos.QuadPart = (LONGLONG)off;
    if (!SetFilePointerEx(in, pos, NULL, FILE_BEGIN)) {
        CloseHandle(out);
        CloseHandle(in);
        return 1;
    }
    while (len > 0) {
        DWORD chunk = (DWORD)(len > sizeof(buf) ? sizeof(buf) : len);
        DWORD rd = 0, wr = 0;
        if (!ReadFile(in, buf, chunk, &rd, NULL) || rd == 0) {
            CloseHandle(out);
            CloseHandle(in);
            return 1;
        }
        if (!WriteFile(out, buf, rd, &wr, NULL) || wr != rd) {
            CloseHandle(out);
            CloseHandle(in);
            return 1;
        }
        len -= rd;
    }
    CloseHandle(out);
    CloseHandle(in);
    return 0;
}

static int find_zip_payload(const wchar_t *self, ULONGLONG *off, ULONGLONG *len)
{
    HANDLE h;
    char head[262144];
    DWORD rd = 0;
    DWORD i;
    unsigned long long zip_len = 0;
    ULONGLONG total;

    total = file_size_of(self);
    if (total < 32)
        return 1;
    h = CreateFileW(
        self,
        GENERIC_READ,
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        NULL,
        OPEN_EXISTING,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    if (h == INVALID_HANDLE_VALUE)
        return 1;
    if (!ReadFile(h, head, sizeof(head), &rd, NULL)) {
        CloseHandle(h);
        return 1;
    }
    CloseHandle(h);
    for (i = 0; i + ZIP_MAGIC_LEN + 8 < rd; i++) {
        if (memcmp(head + i, ZIP_MAGIC, ZIP_MAGIC_LEN) != 0)
            continue;
        memcpy(&zip_len, head + i + ZIP_MAGIC_LEN, 8);
        if (zip_len < 32 || i + ZIP_MAGIC_LEN + 8 + zip_len != total)
            continue;
        if (i + ZIP_MAGIC_LEN + 8 >= rd || head[i + ZIP_MAGIC_LEN + 8] != 'P' ||
            head[i + ZIP_MAGIC_LEN + 9] != 'K')
            continue;
        *off = (ULONGLONG)i + ZIP_MAGIC_LEN + 8;
        *len = (ULONGLONG)zip_len;
        return 0;
    }
    return 1;
}

static int delete_tree(const wchar_t *path)
{
    SHFILEOPSTRUCTW op;
    wchar_t from[MAXP + 2];
    size_t n;
    if (!dir_exists(path) && !file_exists(path))
        return 0;
    n = wcslen(path);
    if (n + 2 >= MAXP)
        return 1;
    memcpy(from, path, (n + 1) * sizeof(wchar_t));
    from[n + 1] = 0;
    ZeroMemory(&op, sizeof(op));
    op.wFunc = FO_DELETE;
    op.pFrom = from;
    op.fFlags = FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT;
    SHFileOperationW(&op);
    return (dir_exists(path) || file_exists(path)) ? 1 : 0;
}

static int copy_file_retry(const wchar_t *src, const wchar_t *dst)
{
    int i;
    for (i = 0; i < 6; i++) {
        if (CopyFileW(src, dst, FALSE))
            return 0;
        Sleep(80);
    }
    return 1;
}

static int copy_tree(const wchar_t *src, const wchar_t *dst)
{
    WIN32_FIND_DATAW fd;
    wchar_t pattern[MAXP], from[MAXP], to[MAXP];
    HANDLE h;
    int rc = 0;

    if (!CreateDirectoryW(dst, NULL) && GetLastError() != ERROR_ALREADY_EXISTS && !dir_exists(dst))
        return 1;
    join2(pattern, MAXP, src, L"*");
    h = FindFirstFileW(pattern, &fd);
    if (h == INVALID_HANDLE_VALUE)
        return 1;
    do {
        if (wcscmp(fd.cFileName, L".") == 0 || wcscmp(fd.cFileName, L"..") == 0)
            continue;
        join2(from, MAXP, src, fd.cFileName);
        join2(to, MAXP, dst, fd.cFileName);
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) {
            if (copy_tree(from, to) != 0) {
                rc = 1;
                break;
            }
        } else if (copy_file_retry(from, to) != 0) {
            rc = 1;
            break;
        }
        pump_ui();
    } while (FindNextFileW(h, &fd));
    FindClose(h);
    return rc;
}

static int copy_contents(const wchar_t *src, const wchar_t *dst)
{
    /* SHFileOperation 拷几千个文件经常悄悄失败，覆盖安装后缺 httpx。 */
    return copy_tree(src, dst);
}

static void ps_quote(wchar_t *out, size_t n, const wchar_t *in)
{
    size_t j = 0, i;
    for (i = 0; in[i] && j + 2 < n; i++) {
        if (in[i] == L'\'') {
            if (j + 3 >= n)
                break;
            out[j++] = L'\'';
            out[j++] = L'\'';
        } else {
            out[j++] = in[i];
        }
    }
    out[j] = 0;
}

static int write_utf16_file(const wchar_t *path, const wchar_t *text)
{
    HANDLE h = CreateFileW(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    unsigned char bom[2] = {0xFF, 0xFE};
    DWORD wr = 0;
    if (h == INVALID_HANDLE_VALUE)
        return 1;
    WriteFile(h, bom, 2, &wr, NULL);
    WriteFile(h, text, (DWORD)(wcslen(text) * sizeof(wchar_t)), &wr, NULL);
    CloseHandle(h);
    return 0;
}

static void make_shortcut(const wchar_t *lnk, const wchar_t *target, const wchar_t *workdir)
{
    IShellLinkW *sl = NULL;
    IPersistFile *pf = NULL;
    wchar_t icon[MAXP];
    if (FAILED(CoCreateInstance(&CLSID_ShellLink, NULL, CLSCTX_INPROC_SERVER, &IID_IShellLinkW, (void **)&sl)))
        return;
    IShellLinkW_SetPath(sl, target);
    IShellLinkW_SetWorkingDirectory(sl, workdir);
    join2(icon, MAXP, workdir, L"app-icon.ico");
    if (file_exists(icon))
        IShellLinkW_SetIconLocation(sl, icon, 0);
    else
        IShellLinkW_SetIconLocation(sl, target, 0);
    IShellLinkW_SetDescription(sl, SHORTCUT_LABEL);
    if (SUCCEEDED(IShellLinkW_QueryInterface(sl, &IID_IPersistFile, (void **)&pf))) {
        IPersistFile_Save(pf, lnk, TRUE);
        IPersistFile_Release(pf);
    }
    IShellLinkW_Release(sl);
    SHChangeNotify(SHCNE_CREATE, SHCNF_PATHW, lnk, NULL);
}

static void remove_shortcut(const wchar_t *dir, const wchar_t *name)
{
    wchar_t lnk[MAXP];
    join2(lnk, MAXP, dir, name);
    if (file_exists(lnk) && DeleteFileW(lnk))
        SHChangeNotify(SHCNE_DELETE, SHCNF_PATHW, lnk, NULL);
}

static void create_shortcuts(const wchar_t *dest)
{
    wchar_t target[MAXP], desk[MAXP], prog[MAXP], lnk[MAXP];
    join2(target, MAXP, dest, L"SORFill.exe");
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_DESKTOPDIRECTORY, NULL, 0, desk))) {
        remove_shortcut(desk, SHORTCUT_NAME_OLD);
        join2(lnk, MAXP, desk, SHORTCUT_NAME);
        make_shortcut(lnk, target, dest);
    }
    if (SUCCEEDED(SHGetFolderPathW(NULL, CSIDL_PROGRAMS, NULL, 0, prog))) {
        remove_shortcut(prog, SHORTCUT_NAME_OLD);
        join2(lnk, MAXP, prog, SHORTCUT_NAME);
        make_shortcut(lnk, target, dest);
    }
}

static HANDLE open_log(const wchar_t *log_path)
{
    SECURITY_ATTRIBUTES sa;
    HANDLE h;
    ZeroMemory(&sa, sizeof(sa));
    sa.nLength = sizeof(sa);
    sa.bInheritHandle = TRUE;
    h = CreateFileW(
        log_path,
        FILE_APPEND_DATA,
        FILE_SHARE_READ,
        &sa,
        OPEN_ALWAYS,
        FILE_ATTRIBUTE_NORMAL,
        NULL);
    return h;
}

static int extract_with_tar(const wchar_t *dest, const wchar_t *zip_name, const wchar_t *log_path)
{
    wchar_t sysdir[MAXP], tar[MAXP], cmd[MAXP * 2];
    HANDLE log;
    int rc;

    GetSystemDirectoryW(sysdir, MAXP);
    join2(tar, MAXP, sysdir, L"tar.exe");
    if (!file_exists(tar)) {
        append_log(log_path, "tar.exe not found");
        return 1;
    }
    _snwprintf(cmd, MAXP * 2, L"\"%s\" -xf \"%s\"", tar, zip_name);
    cmd[MAXP * 2 - 1] = 0;
    append_logw(log_path, cmd);
    log = open_log(log_path);
    rc = run_hidden_wait(cmd, dest, 1, 1, log != INVALID_HANDLE_VALUE ? log : NULL);
    if (log != INVALID_HANDLE_VALUE)
        CloseHandle(log);
    return rc;
}

static int extract_with_powershell(const wchar_t *zip, const wchar_t *dest, const wchar_t *log_path)
{
    wchar_t tmp[MAXP], ps1[MAXP], zip_q[MAXP], dest_q[MAXP], log_q[MAXP];
    wchar_t script[4096], cmd[MAXP * 2];
    HANDLE log;
    int rc;

    GetTempPathW(MAXP, tmp);
    join2(ps1, MAXP, tmp, L"electrical-krow-install.ps1");
    ps_quote(zip_q, MAXP, zip);
    ps_quote(dest_q, MAXP, dest);
    ps_quote(log_q, MAXP, log_path);
    _snwprintf(
        script,
        4096,
        L"$ErrorActionPreference = 'Stop'\n"
        L"try {\n"
        L"  Add-Type -AssemblyName System.IO.Compression.FileSystem\n"
        L"  $zip = '%s'\n"
        L"  $dest = '%s'\n"
        L"  if (Test-Path -LiteralPath $dest) {\n"
        L"    Remove-Item -LiteralPath $dest -Recurse -Force\n"
        L"  }\n"
        L"  [System.IO.Compression.ZipFile]::ExtractToDirectory($zip, $dest)\n"
        L"} catch {\n"
        L"  $_ | Out-File -FilePath '%s' -Append -Encoding utf8\n"
        L"  throw\n"
        L"}\n",
        zip_q,
        dest_q,
        log_q);
    script[4095] = 0;
    if (write_utf16_file(ps1, script)) {
        append_log(log_path, "cannot write powershell script");
        return 1;
    }
    _snwprintf(cmd, MAXP * 2, L"powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%s\"", ps1);
    cmd[MAXP * 2 - 1] = 0;
    append_logw(log_path, cmd);
    log = open_log(log_path);
    rc = run_hidden_wait(cmd, NULL, 1, 1, log != INVALID_HANDLE_VALUE ? log : NULL);
    if (log != INVALID_HANDLE_VALUE)
        CloseHandle(log);
    DeleteFileW(ps1);
    return rc;
}

static int extract_payload(const wchar_t *zip_path, const wchar_t *unpack, const wchar_t *log_path)
{
    wchar_t nested[MAXP];
    int i;

    stop_dir_processes(unpack);
    for (i = 0; i < 3 && dir_exists(unpack); i++) {
        delete_tree(unpack);
        Sleep(200);
    }
    if (!CreateDirectoryW(unpack, NULL) && GetLastError() != ERROR_ALREADY_EXISTS)
        return 1;
    join2(nested, MAXP, unpack, L"_payload.zip");
    if (!CopyFileW(zip_path, nested, FALSE))
        return 1;
    if (extract_with_tar(unpack, L"_payload.zip", log_path) == 0) {
        DeleteFileW(nested);
        return 0;
    }
    append_log(log_path, "tar extract failed, trying powershell");
    DeleteFileW(nested);
    return extract_with_powershell(zip_path, unpack, log_path);
}

static int install_from_self(const wchar_t *self)
{
    wchar_t local[MAXP], dest[MAXP], tmp[MAXP], log_path[MAXP], zip_path[MAXP];
    wchar_t unpack[MAXP], config[MAXP], saved[MAXP], runpy[MAXP];
    ULONGLONG zip_off = 0, zip_len = 0;
    int i;

    if (GetEnvironmentVariableW(L"LOCALAPPDATA", local, MAXP) == 0) {
        MessageBoxW(NULL, L"找不到 LOCALAPPDATA。", TITLE, MB_OK | MB_ICONERROR);
        return 1;
    }
    join2(dest, MAXP, local, L"electrical-krow-app");
    GetTempPathW(MAXP, tmp);
    join2(log_path, MAXP, tmp, L"electrical-krow-install.log");
    join2(zip_path, MAXP, tmp, L"electrical-krow-payload.zip");
    join2(unpack, MAXP, tmp, L"electrical-krow-unpack");
    join2(saved, MAXP, tmp, L"electrical-krow-config.ini");
    DeleteFileW(log_path);
    append_log(log_path, "install start");
    append_logw(log_path, self);
    append_logw(log_path, dest);

    CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    status_show(L"正在安装到本机，第一次大约几十秒，请不要关闭。");

    if (find_zip_payload(self, &zip_off, &zip_len) != 0) {
        CoUninitialize();
        return fail_install(log_path, L"安装包格式不对。请改用 zip 解压安装，或重新下载完整 exe。");
    }
    append_log(log_path, "found zip payload");
    status_show(L"正在写出安装文件…");
    if (copy_range(self, zip_off, zip_len, zip_path) != 0) {
        CoUninitialize();
        return fail_install(log_path, L"无法写出解压文件。请检查磁盘空间，或把杀毒软件加白后重试。");
    }

    status_show(L"正在解压安装文件，请稍候…");
    if (extract_payload(zip_path, unpack, log_path) != 0) {
        DeleteFileW(zip_path);
        CoUninitialize();
        return fail_install(
            log_path,
            L"解压失败。常见原因：杀毒拦截、PowerShell 被禁用、或 Windows 太旧没有 tar。");
    }
    DeleteFileW(zip_path);
    join2(runpy, MAXP, unpack, L"run.py");
    if (!file_exists(runpy)) {
        CoUninitialize();
        return fail_install(log_path, L"解压完成但缺少 run.py。请改用 zip 安装。");
    }

    join2(config, MAXP, dest, L"config.ini");
    DeleteFileW(saved);
    if (file_exists(config))
        CopyFileW(config, saved, FALSE);

    stop_dir_processes(dest);
    for (i = 0; i < 4 && dir_exists(dest); i++) {
        delete_tree(dest);
        Sleep(250);
    }

    if (!dir_exists(dest)) {
        if (!MoveFileW(unpack, dest)) {
            append_log(log_path, "MoveFile unpack -> dest failed, copying");
            if (!CreateDirectoryW(dest, NULL) && GetLastError() != ERROR_ALREADY_EXISTS) {
                CoUninitialize();
                return fail_install(log_path, L"无法创建安装目录。");
            }
            if (copy_contents(unpack, dest) != 0) {
                CoUninitialize();
                return fail_install(log_path, L"无法写入安装目录。请把杀毒软件加白后重试。");
            }
            delete_tree(unpack);
        }
    } else {
        append_log(log_path, "old dest still present, overlay copy");
        if (copy_contents(unpack, dest) != 0) {
            CoUninitialize();
            return fail_install(
                log_path,
                L"无法覆盖旧安装目录。请关掉出表窗口和资源管理器里打开的安装文件夹后再双击 exe。");
        }
        delete_tree(unpack);
    }

    if (file_exists(saved)) {
        wchar_t bak[MAXP];
        join2(bak, MAXP, dest, L"config.ini.bak");
        CopyFileW(saved, bak, FALSE);
        DeleteFileW(saved);
        append_log(log_path, "kept packaged config.ini; old saved as config.ini.bak");
    }

    join2(runpy, MAXP, dest, L"run.py");
    if (!file_exists(runpy)) {
        CoUninitialize();
        return fail_install(log_path, L"安装目录不完整。请改用 zip 安装。");
    }
    {
        wchar_t httpx[MAXP];
        join2(httpx, MAXP, dest, L"python\\Lib\\site-packages\\httpx\\__init__.py");
        if (!file_exists(httpx)) {
            CoUninitialize();
            return fail_install(
                log_path,
                L"安装后缺少 httpx。请关掉出表窗口，删掉 %LOCALAPPDATA%\\electrical-krow-app 后再装。");
        }
    }

    create_shortcuts(dest);
    append_log(log_path, "install ok");
    CoUninitialize();
    return start_from_dir(dest);
}

static int start_or_install(void)
{
    wchar_t self[MAXP], dir[MAXP], runpy[MAXP];
    if (!GetModuleFileNameW(NULL, self, MAXP))
        return 1;
    status_show(L"正在启动电子电器智能体，请稍候…");
    dirname_of(dir, MAXP, self);
    join2(runpy, MAXP, dir, L"run.py");
    if (file_exists(runpy))
        return start_from_dir(dir);
    if (file_size_of(self) > 1024ull * 1024ull)
        return install_from_self(self);
    status_close();
    MessageBoxW(NULL, L"请使用完整安装包（exe）或解压 zip 后启动。", TITLE, MB_OK | MB_ICONERROR);
    return 1;
}

int WINAPI WinMain(HINSTANCE inst, HINSTANCE prev, LPSTR cmd, int show)
{
    (void)inst;
    (void)prev;
    (void)cmd;
    (void)show;
#ifdef STOP_APP
    return stop_listener();
#else
    return start_or_install();
#endif
}
