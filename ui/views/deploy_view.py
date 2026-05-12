import os
import stat
import threading
import uuid
import paramiko
import customtkinter as ctk
import tkinter.messagebox as messagebox

class DockerSFTPWrapper:

    def __init__(self, ssh_client, docker_name):
        self.ssh = ssh_client
        self.docker_name = docker_name

    class _MockAttr:

        def __init__(self, is_dir, size, filename):
            self.st_mode = stat.S_IFDIR if is_dir else stat.S_IFREG
            self.st_size = size
            self.filename = filename

    def listdir_attr(self, path):
        clean_path = path.replace('"', '\\"')
        cmd = f'docker exec "{self.docker_name}" sh -c "ls -l \\"{clean_path}\\" | tail -n +2"'
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        err = stderr.read().decode().strip()
        if stdout.channel.recv_exit_status() != 0:
            raise FileNotFoundError(f'Docker ls error: {err}')
        items = []
        for line in stdout.read().decode().splitlines():
            if not line.strip():
                continue
            parts = line.split(None, 8)
            if len(parts) >= 9:
                perms = parts[0]
                size = int(parts[4])
                filename = parts[8]
                is_dir = perms.startswith('d')
                items.append(self._MockAttr(is_dir, size, filename))
        return items

    def stat(self, path):
        clean_path = path.replace('"', '\\"')
        cmd = f'docker exec "{self.docker_name}" stat -c "%F|%s" \\"{clean_path}\\"'
        stdin, stdout, stderr = self.ssh.exec_command(cmd)
        if stdout.channel.recv_exit_status() != 0:
            raise FileNotFoundError(f'Docker stat error: {stderr.read().decode()}')
        output = stdout.read().decode().strip()
        type_str, size_str = output.split('|', 1)
        is_dir = 'directory' in type_str.lower()
        return self._MockAttr(is_dir, int(size_str), os.path.basename(path))

    def get(self, remote_path, local_path):
        import time
        import uuid
        tmp_name = f'zerosync_dl_{uuid.uuid4().hex}.tmp'
        tmp_host_path = f'/tmp/{tmp_name}'
        clean_remote = remote_path.replace('"', '\\"')
        cmd1 = f'docker cp "{self.docker_name}:{clean_remote}" "{tmp_host_path}"'
        _, stdout1, stderr1 = self.ssh.exec_command(cmd1)
        if stdout1.channel.recv_exit_status() != 0:
            raise RuntimeError(f'Docker cp error: {stderr1.read().decode()}')
        sftp = self.ssh.open_sftp()
        try:
            sftp.get(tmp_host_path, local_path)
        finally:
            sftp.close()
            self.ssh.exec_command(f'rm -f "{tmp_host_path}"')

    def close(self):
        pass

class RemoteDownloaderDialog(ctk.CTkToplevel):

    def __init__(self, master, config_dict: dict, on_close_callback, **kwargs):
        super().__init__(master, **kwargs)
        self.title('远端文件拉取器')
        self.geometry('850x600')
        self.transient(master)
        self.grab_set()
        self.config_dict = config_dict
        self.on_close_callback = on_close_callback
        self.base_remote_dir = config_dict.get('remote_dir', '/')
        self.local_dir = config_dict.get('local_dir', '')
        self.current_remote_path = self.base_remote_dir
        self.sftp = None
        self.ssh = None
        self.item_vars = {}
        self._is_loading = False
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.top_frame = ctk.CTkFrame(self)
        self.top_frame.grid(row=0, column=0, sticky='ew', padx=10, pady=10)
        self.up_btn = ctk.CTkButton(self.top_frame, text='返回上级', width=60, command=self._go_up)
        self.up_btn.pack(side='left', padx=5, pady=5)
        self.path_label = ctk.CTkLabel(self.top_frame, text=self.current_remote_path, font=('Consolas', 14, 'bold'))
        self.path_label.pack(side='left', padx=10, pady=5)
        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.grid(row=1, column=0, sticky='nsew', padx=10, pady=5)
        self.bottom_frame = ctk.CTkFrame(self)
        self.bottom_frame.grid(row=2, column=0, sticky='ew', padx=10, pady=10)
        self.status_label = ctk.CTkLabel(self.bottom_frame, text='正在连接服务器...', text_color='#F1C40F')
        self.status_label.pack(side='left', padx=10, pady=10)
        self.download_btn = ctk.CTkButton(self.bottom_frame, text='下载选中文件', font=('Roboto', 14, 'bold'), fg_color='#27AE60', hover_color='#1E8449', command=self._start_download)
        self.download_btn.pack(side='right', padx=10, pady=10)
        self.keep_struct_var = ctk.BooleanVar(value=True)
        self.keep_struct_cb = ctk.CTkCheckBox(self.bottom_frame, text='保持远端目录结构 (如果取消，将直接保存在本地同步根目录下)', variable=self.keep_struct_var, font=('Roboto', 12))
        self.keep_struct_cb.pack(side='right', padx=20, pady=10)
        self.protocol('WM_DELETE_WINDOW', self._on_closing)
        threading.Thread(target=self._connect_and_load, daemon=True).start()

    def _connect_and_load(self):
        self._is_loading = True
        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            ssh_conf = self.config_dict.get('ssh', {})
            if ssh_conf.get('key_path'):
                self.ssh.connect(ssh_conf.get('hostname'), port=int(ssh_conf.get('port', 22)), username=ssh_conf.get('username'), key_filename=ssh_conf.get('key_path'), passphrase=ssh_conf.get('password'))
            else:
                self.ssh.connect(ssh_conf.get('hostname'), port=int(ssh_conf.get('port', 22)), username=ssh_conf.get('username'), password=ssh_conf.get('password'))
            docker_name = self.config_dict.get('docker_name', '')
            if docker_name:
                self.sftp = DockerSFTPWrapper(self.ssh, docker_name)
            else:
                self.sftp = self.ssh.open_sftp()
            self._load_directory(self.current_remote_path)
        except Exception as e:
            self._is_loading = False
            self.after(0, lambda: self.status_label.configure(text=f'连接失败: {e}', text_color='#E74C3C'))

    def _load_directory(self, path):
        self.current_remote_path = path
        self.after(0, lambda: self.path_label.configure(text=path))
        try:
            items = self.sftp.listdir_attr(path)
            items.sort(key=lambda x: (not stat.S_ISDIR(x.st_mode), x.filename))
            self.after(0, lambda: self._render_items(items))
        except Exception as e:
            e_str = str(e)
            self._is_loading = False
            self.after(0, lambda: self.status_label.configure('读取错误', f'无法读取目录: {e_str}', text_color='#E74C3C'))

    def _render_items(self, items):
        for widget in self.list_frame.winfo_children():
            widget.destroy()
        self.item_vars.clear()
        for item in items:
            row_frame = ctk.CTkFrame(self.list_frame, fg_color='transparent')
            row_frame.pack(fill='x', pady=2)
            is_dir = stat.S_ISDIR(item.st_mode)
            icon = '📁' if is_dir else '📄'
            var = ctk.BooleanVar(value=False)
            self.item_vars[item.filename] = {'var': var, 'is_dir': is_dir}
            cb = ctk.CTkCheckBox(row_frame, text='', variable=var, width=20)
            cb.pack(side='left', padx=5)
            if is_dir:
                btn = ctk.CTkButton(row_frame, text=f'{icon} {item.filename}', fg_color='transparent', text_color=('gray10', 'gray90'), anchor='w', hover_color=('gray75', 'gray25'), command=lambda p=item.filename: self._enter_dir(p))
                btn.pack(side='left', fill='x', expand=True)
            else:
                lbl = ctk.CTkLabel(row_frame, text=f'{icon} {item.filename}', anchor='w')
                lbl.pack(side='left', fill='x', expand=True)
                size_mb = item.st_size / (1024 * 1024)
                ctk.CTkLabel(row_frame, text=f'{size_mb:.2f} MB', text_color='gray').pack(side='right', padx=10)
        self._is_loading = False
        self.status_label.configure(text='已就绪，请勾选需要下载的文件', text_color='#2ECC71')

    def _enter_dir(self, folder_name):
        if self._is_loading:
            return
        self._is_loading = True
        self.status_label.configure(text='加载目录中...', text_color='#F1C40F')
        new_path = f'{self.current_remote_path}/{folder_name}'.replace('//', '/')
        threading.Thread(target=self._load_directory, args=(new_path,), daemon=True).start()

    def _go_up(self):
        if self._is_loading:
            return
        if self.current_remote_path != self.base_remote_dir and self.current_remote_path != '/':
            self._is_loading = True
            self.status_label.configure(text='加载上级目录中...', text_color='#F1C40F')
            parent_path = os.path.dirname(self.current_remote_path)
            threading.Thread(target=self._load_directory, args=(parent_path,), daemon=True).start()

    def _start_download(self):
        selected_files = [name for name, data in self.item_vars.items() if data['var'].get()]
        if not selected_files:
            messagebox.showwarning('提示', '请至少勾选一个文件或文件夹！')
            return
        keep_structure = self.keep_struct_var.get()
        conflicts = []
        download_tasks = []
        for name in selected_files:
            remote_item_path = f'{self.current_remote_path}/{name}'.replace('//', '/')
            if keep_structure:
                rel_path = os.path.relpath(remote_item_path, self.base_remote_dir).replace('\\', '/')
                local_item_path = os.path.normpath(os.path.join(self.local_dir, rel_path))
            else:
                local_item_path = os.path.normpath(os.path.join(self.local_dir, name))
            download_tasks.append((remote_item_path, local_item_path))
            if os.path.exists(local_item_path):
                conflicts.append(name)
        if conflicts:
            conflict_str = ', '.join(conflicts[:3]) + (' 等' if len(conflicts) > 3 else '')
            if not messagebox.askyesno('覆盖警告', f'以下文件或目录在本地已存在：\n{conflict_str}\n\n是否继续并强制覆盖它们？'):
                return
        self.download_btn.configure(state='disabled', text='正在下载...')
        threading.Thread(target=self._download_worker, args=(download_tasks,), daemon=True).start()

    def _download_worker(self, download_tasks):
        try:
            for remote_path, local_path in download_tasks:
                name = os.path.basename(remote_path)
                self.after(0, lambda n=name: self.status_label.configure(text=f'正在拉取: {n} ...', text_color='#F1C40F'))
                self._recursive_download(remote_path, local_path)
            self.after(0, lambda: self.status_label.configure(text='所有选中文件下载完成！您可以关闭此窗口恢复同步。', text_color='#2ECC71'))
        except Exception as e:
            self.after(0, lambda: self.status_label.configure(text=f'下载中断: {e}', text_color='#E74C3C'))
        finally:
            self.after(0, lambda: self.download_btn.configure(state='normal', text='下载选中文件'))

    def _recursive_download(self, remote_path, local_path):
        attr = self.sftp.stat(remote_path)
        if stat.S_ISDIR(attr.st_mode):
            os.makedirs(local_path, exist_ok=True)
            for item in self.sftp.listdir_attr(remote_path):
                self._recursive_download(remote_path + '/' + item.filename, os.path.join(local_path, item.filename))
        else:
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            self.sftp.get(remote_path, local_path)

    def _on_closing(self):
        if self.sftp:
            self.sftp.close()
        if self.ssh:
            self.ssh.close()
        self.on_close_callback()
        self.destroy()