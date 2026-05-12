import json
import os
import customtkinter as ctk
import tkinter.messagebox as messagebox
from tkinter import filedialog
import threading
CONFIG_FILE = 'config.json'

class ServerDeployDialog(ctk.CTkToplevel):

    def __init__(self, master, remote_dir: str, port: int, agent_dir: str, docker_name: str, ssh_config: dict, on_confirm_callback, **kwargs):
        super().__init__(master, **kwargs)
        self.title('安全连接检验：请确保远端服务已就绪')
        self.geometry('780x520')
        self.minsize(700, 480)
        self.transient(master)
        self.grab_set()
        self.agent_dir = agent_dir
        self.docker_name = docker_name
        self.ssh_config = ssh_config
        self.on_confirm_callback = on_confirm_callback
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(4, weight=1)
        ctk.CTkLabel(self, text='连接前校验：服务器守护进程状态', font=('Roboto', 20, 'bold'), text_color='#F39C12').grid(row=0, column=0, sticky='w', padx=30, pady=(20, 5))
        target_env = f'Docker 容器 {docker_name}' if docker_name else '服务器宿主机'
        ctk.CTkLabel(self, text=f'请确保同步核心组件已部署至 {target_env} 的 {agent_dir} 目录。\n可点击自动部署，并手动执行以下终端指令：', font=('Roboto', 14), text_color='gray75', justify='left').grid(row=1, column=0, sticky='w', padx=30, pady=(0, 15))
        upload_frame = ctk.CTkFrame(self, fg_color='transparent')
        upload_frame.grid(row=2, column=0, sticky='ew', padx=30, pady=(0, 15))
        self.upload_btn = ctk.CTkButton(upload_frame, text='自动部署核心组件', font=('Roboto', 13, 'bold'), width=160, height=32, command=self._start_upload)
        self.upload_btn.pack(side='left')
        self.upload_status = ctk.CTkLabel(upload_frame, text='等待执行...', text_color='gray60', font=('Consolas', 12))
        self.upload_status.pack(side='left', padx=15)
        cmd_frame = ctk.CTkFrame(self, fg_color='#1A1A1A', corner_radius=8)
        cmd_frame.grid(row=3, column=0, sticky='ew', padx=30)
        cmd_frame.grid_columnconfigure(0, weight=1)
        cmd1 = f'mkdir -p {agent_dir} && cd {agent_dir} && pip install grpcio grpcio-tools zstandard blake3'
        cmd2 = f'cd {agent_dir} && nohup python3 server_template.py --port {port} > zerosync.log 2>&1 &'
        cmd3 = f'pkill -9 -f "python3 server_template.py --port {port}"'
        entry_kwargs = {'font': ('Consolas', 12), 'text_color': '#A9B7C6', 'fg_color': '#2B2B2B', 'border_width': 0, 'height': 30}
        btn_kwargs = {'text': 'Copy', 'width': 60, 'height': 30, 'font': ('Roboto', 12, 'bold'), 'fg_color': '#4A4A4A', 'hover_color': '#5A5A5A'}
        ctk.CTkLabel(cmd_frame, text='[1] 安装底层依赖环境', font=('Consolas', 12, 'bold'), text_color='#2ECC71').grid(row=0, column=0, sticky='w', padx=15, pady=(15, 5))
        self.cmd1_entry = ctk.CTkEntry(cmd_frame, **entry_kwargs)
        self.cmd1_entry.insert(0, cmd1)
        self.cmd1_entry.configure(state='readonly')
        self.cmd1_entry.grid(row=1, column=0, sticky='ew', padx=(15, 10), pady=(0, 15))
        ctk.CTkButton(cmd_frame, command=lambda: self._copy_to_clipboard(cmd1), **btn_kwargs).grid(row=1, column=1, padx=(0, 15), pady=(0, 15))
        ctk.CTkLabel(cmd_frame, text='[2] 后台拉起守护进程', font=('Consolas', 12, 'bold'), text_color='#2ECC71').grid(row=2, column=0, sticky='w', padx=15, pady=(0, 5))
        self.cmd2_entry = ctk.CTkEntry(cmd_frame, **entry_kwargs)
        self.cmd2_entry.insert(0, cmd2)
        self.cmd2_entry.configure(state='readonly')
        self.cmd2_entry.grid(row=3, column=0, sticky='ew', padx=(15, 10), pady=(0, 15))
        ctk.CTkButton(cmd_frame, command=lambda: self._copy_to_clipboard(cmd2), **btn_kwargs).grid(row=3, column=1, padx=(0, 15), pady=(0, 15))
        ctk.CTkLabel(cmd_frame, text='[3] 强制结束旧进程 (端口冲突时备用)', font=('Consolas', 12, 'bold'), text_color='#E74C3C').grid(row=4, column=0, sticky='w', padx=15, pady=(0, 5))
        self.cmd3_entry = ctk.CTkEntry(cmd_frame, **entry_kwargs)
        self.cmd3_entry.insert(0, cmd3)
        self.cmd3_entry.configure(state='readonly')
        self.cmd3_entry.grid(row=5, column=0, sticky='ew', padx=(15, 10), pady=(0, 15))
        ctk.CTkButton(cmd_frame, command=lambda: self._copy_to_clipboard(cmd3), text='Copy', width=60, height=30, font=('Roboto', 12, 'bold'), fg_color='#922B21', hover_color='#C0392B').grid(row=5, column=1, padx=(0, 15), pady=(0, 15))
        btn_frame = ctk.CTkFrame(self, fg_color='transparent')
        btn_frame.grid(row=4, column=0, sticky='ew', padx=30, pady=20)
        btn_frame.grid_columnconfigure(0, weight=1)
        has_agent_config = False
        if os.path.exists('skills.json'):
            try:
                with open('skills.json', 'r', encoding='utf-8') as f:
                    sd = json.load(f)
                    if sd.get('active_agent') and sd.get('active_agent') in sd.get('agents', {}):
                        has_agent_config = True
            except Exception:
                pass
        self.inject_agent_var = ctk.BooleanVar()
        self.agent_switch = ctk.CTkSwitch(btn_frame, text='连接时挂载 Agent 助手桥接', variable=self.inject_agent_var, font=('Roboto', 13), progress_color='#8E44AD')
        self.agent_switch.grid(row=0, column=0, sticky='w')
        if has_agent_config:
            self.agent_switch.configure(state='normal')
            self.inject_agent_var.set(True)
        else:
            self.agent_switch.configure(state='disabled', text='Agent 助手挂载受限 (未配置智能体路径)')
            self.inject_agent_var.set(False)
        cancel_btn = ctk.CTkButton(btn_frame, text='取消', width=80, height=36, fg_color='transparent', border_width=1, text_color=('gray10', 'gray90'), command=self.destroy)
        cancel_btn.grid(row=0, column=1, padx=(0, 15))
        confirm_btn = ctk.CTkButton(btn_frame, text='服务已就绪，立即连接', font=('Roboto', 13, 'bold'), height=36, command=self._confirm_and_close)
        confirm_btn.grid(row=0, column=2)

    def _start_upload(self):
        self.upload_btn.configure(state='disabled', text='正在上传...')
        self.upload_status.configure(text='正在连接服务器并创建目录...', text_color='#F1C40F')
        threading.Thread(target=self._sftp_upload_worker, daemon=True).start()

    def _sftp_upload_worker(self):
        import paramiko
        try:
            ssh = paramiko.SSHClient()
            ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            key_path = self.ssh_config.get('key_path')
            password = self.ssh_config.get('password')
            username = self.ssh_config.get('username')
            hostname = self.ssh_config.get('hostname')
            port = int(self.ssh_config.get('port', 22))
            if key_path:
                ssh.connect(hostname, port=port, username=username, key_filename=key_path, passphrase=password)
            else:
                ssh.connect(hostname, port=port, username=username, password=password)
            files_to_upload = [('sync_pb2.py', 'sync_pb2.py'), ('sync_pb2_grpc.py', 'sync_pb2_grpc.py'), ('deploy/server_template.py', 'server_template.py'), ('deploy/requirements.txt', 'requirements.txt')]
            sftp = ssh.open_sftp()
            if getattr(self, 'docker_name', None):
                import time
                host_tmp = f'/tmp/zerosync_pkg_{int(time.time())}'
                _, stdout, _ = ssh.exec_command(f'mkdir -p {host_tmp}')
                stdout.channel.recv_exit_status()
                for local_f, remote_f in files_to_upload:
                    if os.path.exists(local_f):
                        self.after(0, lambda f=remote_f: self.upload_status.configure(text=f'正在推送: {f} (至宿主机) ...'))
                        sftp.put(local_f, f'{host_tmp}/{remote_f}')
                self.after(0, lambda: self.upload_status.configure(text='正在将文件 cp 进 Docker 容器...'))
                docker_cmd = f'docker exec -u root {self.docker_name} mkdir -p {self.agent_dir} && docker cp {host_tmp}/. {self.docker_name}:{self.agent_dir}/ && rm -rf {host_tmp}'
                _, stdout, stderr = ssh.exec_command(docker_cmd)
                exit_status = stdout.channel.recv_exit_status()
                if exit_status != 0:
                    err_msg = stderr.read().decode('utf-8').strip()
                    raise Exception(f'Docker CP 失败 ({exit_status}): {err_msg}')
            else:
                _, stdout, _ = ssh.exec_command(f'mkdir -p {self.agent_dir}')
                stdout.channel.recv_exit_status()
                for local_f, remote_f in files_to_upload:
                    if os.path.exists(local_f):
                        remote_path = f'{self.agent_dir}/{remote_f}'.replace('//', '/')
                        self.after(0, lambda f=remote_f: self.upload_status.configure(text=f'正在推送: {f} ...'))
                        sftp.put(local_f, remote_path)
            sftp.close()
            ssh.close()
            self.after(0, lambda: self.upload_status.configure(text=f'✅ 核心程序已成功推送至 {self.agent_dir}！', text_color='#2ECC71'))
            self.after(0, lambda: self.upload_btn.configure(text='重新上传', state='normal'))
        except Exception as e:
            self.after(0, lambda: self.upload_status.configure(text=f'❌ 上传失败: {e}', text_color='#E74C3C'))
            self.after(0, lambda: self.upload_btn.configure(text='重试上传', state='normal', fg_color='#C0392B'))

    def _copy_to_clipboard(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)

    def _confirm_and_close(self):
        inject_agent = self.inject_agent_var.get()
        self.on_confirm_callback(inject_agent)
        self.destroy()

class HomeView(ctk.CTkFrame):

    def __init__(self, master, on_connect_success, **kwargs):
        super().__init__(master, corner_radius=0, fg_color='transparent', **kwargs)
        self.on_connect_success = on_connect_success
        self.config_data = {}
        self.current_profile = None
        self.original_remote_dir = ''
        self.grid_rowconfigure((0, 4), weight=1)
        self.grid_columnconfigure((0, 2), weight=1)
        self.content_frame = ctk.CTkFrame(self, width=600, corner_radius=15)
        self.content_frame.grid(row=1, column=1, sticky='nsew', padx=20, pady=20)
        self.content_frame.grid_columnconfigure(1, weight=1)
        self.title_label = ctk.CTkLabel(self.content_frame, text='连接到远端节点', font=('Roboto', 26, 'bold'))
        self.title_label.grid(row=0, column=0, columnspan=3, pady=(30, 20))
        ctk.CTkLabel(self.content_frame, text='选择服务器方案:', font=('Roboto', 14, 'bold')).grid(row=1, column=0, sticky='e', padx=20, pady=10)
        self.profile_var = ctk.StringVar(value='正在加载...')
        self.profile_menu = ctk.CTkOptionMenu(self.content_frame, variable=self.profile_var, command=self._on_profile_selected, width=300, height=35)
        self.profile_menu.grid(row=1, column=1, columnspan=2, sticky='w', padx=10, pady=10)
        ctk.CTkLabel(self.content_frame, text='本地挂载目录:', font=('Roboto', 14)).grid(row=2, column=0, sticky='e', padx=20, pady=15)
        self.local_dir_entry = ctk.CTkEntry(self.content_frame, placeholder_text='请选择本地要同步的文件夹', width=300, height=35)
        self.local_dir_entry.grid(row=2, column=1, sticky='w', padx=10, pady=15)
        self.browse_btn = ctk.CTkButton(self.content_frame, text='浏览...', width=80, height=35, command=self._browse_local_dir)
        self.browse_btn.grid(row=2, column=2, sticky='w', padx=(0, 20), pady=15)
        ctk.CTkLabel(self.content_frame, text='远端目标目录:', font=('Roboto', 14)).grid(row=3, column=0, sticky='e', padx=20, pady=15)
        self.remote_dir_entry = ctk.CTkEntry(self.content_frame, placeholder_text='Linux 服务器上的绝对路径', width=300, height=35)
        self.remote_dir_entry.grid(row=3, column=1, columnspan=2, sticky='w', padx=10, pady=15)
        self.connect_btn = ctk.CTkButton(self.content_frame, text='建立安全连接', font=('Roboto', 16, 'bold'), height=50, width=300, fg_color='#27AE60', hover_color='#1E8449', command=self._on_connect_clicked)
        self.connect_btn.grid(row=4, column=0, columnspan=3, pady=(30, 40))
        self._load_config()

    def _load_config(self):
        if not os.path.exists(CONFIG_FILE):
            self.profile_var.set('未找到配置文件')
            self.profile_menu.configure(state='disabled', values=[])
            return
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                self.config_data = json.load(f)
            profiles = self.config_data.get('profiles', [])
            if not profiles:
                self.profile_var.set('配置为空，请先前往配置页添加')
                self.profile_menu.configure(state='disabled', values=[])
                return
            profile_names = [p.get('name', 'Unknown') for p in profiles]
            self.profile_menu.configure(state='normal', values=profile_names)
            active_name = self.config_data.get('active_profile', '')
            if active_name in profile_names:
                self.profile_var.set(active_name)
                self._on_profile_selected(active_name)
            else:
                self.profile_var.set(profile_names[0])
                self._on_profile_selected(profile_names[0])
        except Exception as e:
            self.profile_var.set(f'配置解析失败')
            self.profile_menu.configure(state='disabled', values=[])

    def _on_profile_selected(self, selected_name: str):
        for prof in self.config_data.get('profiles', []):
            if prof.get('name') == selected_name:
                self.current_profile = prof
                self.original_remote_dir = prof.get('remote_dir', '')
                self.local_dir_entry.delete(0, 'end')
                self.local_dir_entry.insert(0, prof.get('local_dir', ''))
                self.remote_dir_entry.delete(0, 'end')
                self.remote_dir_entry.insert(0, self.original_remote_dir)
                break

    def _browse_local_dir(self):
        selected_dir = filedialog.askdirectory(title='选择本地同步目录')
        if selected_dir:
            self.local_dir_entry.delete(0, 'end')
            self.local_dir_entry.insert(0, selected_dir)

    def _on_connect_clicked(self):
        if not self.current_profile:
            messagebox.showwarning('警告', '请先选择一个有效的服务器方案。')
            return
        local_dir = self.local_dir_entry.get().strip()
        remote_dir = self.remote_dir_entry.get().strip()
        if not local_dir or not remote_dir:
            messagebox.showwarning('警告', '本地目录和远端目录都不能为空！')
            return
        if not os.path.exists(local_dir):
            messagebox.showerror('错误', f'本地目录不存在，请检查路径:\n{local_dir}')
            return
        try:
            profile_name = self.current_profile.get('name')
            for prof in self.config_data.get('profiles', []):
                if prof.get('name') == profile_name:
                    prof['local_dir'] = local_dir
                    prof['remote_dir'] = remote_dir
                    break
            self.config_data['active_profile'] = profile_name
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4, ensure_ascii=False)
        except Exception as e:
            if hasattr(self, 'master') and hasattr(self.master, 'views') and ('workspace' in self.master.views):
                self.master.views['workspace'].append_log(f'Failed to save config updates: {e}', 'WARNING')
            else:
                import logging
                logging.warning(f'Failed to save config updates: {e}')
        final_config = self.current_profile.copy()
        final_config['local_dir'] = local_dir
        final_config['remote_dir'] = remote_dir
        port = final_config.get('grpc_port', 50051)
        agent_dir = final_config.get('agent_dir', '~/.zerosync')
        docker_name = final_config.get('docker_name', '')

        def _execute_connection(inject_agent: bool):
            final_config['enable_agent'] = inject_agent
            self.connect_btn.configure(state='disabled', text='连接中...')
            self.after(500, lambda: self.on_connect_success(final_config))
            self.after(600, lambda: self.connect_btn.configure(state='normal', text='建立安全连接'))
        ssh_config = final_config.get('ssh', {})
        ssh_config['skill_export_path'] = final_config.get('skill_export_path', '')
        dialog = ServerDeployDialog(master=self.winfo_toplevel(), remote_dir=remote_dir, port=port, agent_dir=agent_dir, docker_name=docker_name, ssh_config=ssh_config, on_confirm_callback=_execute_connection)

    def refresh(self):
        self._load_config()