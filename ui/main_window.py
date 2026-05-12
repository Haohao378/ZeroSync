import sys
import ctypes
import customtkinter as ctk
from ui.views.home_view import HomeView
from ui.views.config_view import ConfigView
from ui.views.workspace_view import WorkspaceView
from ui.views.agent_config_view import AgentConfigView

def enable_dpi_awareness():
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
ctk.set_appearance_mode('Dark')
ctk.set_default_color_theme('blue')

class ZeroSyncApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title('ZeroSync')
        self.geometry('950x650')
        self.minsize(850, 550)
        self.is_connected = False
        self.active_config = None
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.sidebar_frame = ctk.CTkFrame(self, width=220, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky='nsew')
        self.sidebar_frame.grid_rowconfigure(6, weight=1)
        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text='ZeroSync', font=('Roboto', 22, 'bold'))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(25, 30))
        self.nav_home_btn = ctk.CTkButton(self.sidebar_frame, text='节点连接', font=('Roboto', 14), fg_color='transparent', text_color=('gray10', 'gray90'), anchor='w', command=lambda: self.select_view('home'))
        self.nav_home_btn.grid(row=1, column=0, padx=20, pady=10, sticky='ew')
        self.nav_workspace_btn = ctk.CTkButton(self.sidebar_frame, text='同步工作台', font=('Roboto', 14), fg_color='transparent', text_color='gray50', anchor='w', state='disabled', command=lambda: self.select_view('workspace'))
        self.nav_workspace_btn.grid(row=2, column=0, padx=20, pady=10, sticky='ew')
        self.nav_config_btn = ctk.CTkButton(self.sidebar_frame, text='服务器配置', font=('Roboto', 14), fg_color='transparent', text_color=('gray10', 'gray90'), anchor='w', command=lambda: self.select_view('config'))
        self.nav_config_btn.grid(row=3, column=0, padx=20, pady=10, sticky='ew')
        self.nav_agent_btn = ctk.CTkButton(self.sidebar_frame, text='智能体助手', font=('Roboto', 14), fg_color='transparent', text_color=('gray10', 'gray90'), anchor='w', command=lambda: self.select_view('agent'))
        self.nav_agent_btn.grid(row=4, column=0, padx=20, pady=10, sticky='ew')
        self.conn_status_label = ctk.CTkLabel(self.sidebar_frame, text='当前未连接', text_color='#E74C3C', font=('Roboto', 12), width=180, wraplength=170, anchor='w', justify='left')
        self.conn_status_label.grid(row=7, column=0, padx=20, pady=20, sticky='w')
        self.views = {}
        self.views['home'] = HomeView(self, on_connect_success=self.handle_connection_success)
        self.views['home'].grid(row=0, column=1, sticky='nsew')
        self.views['config'] = ConfigView(self)
        self.views['config'].grid(row=0, column=1, sticky='nsew')
        self.views['workspace'] = WorkspaceView(self)
        self.views['workspace'].grid(row=0, column=1, sticky='nsew')
        self.views['agent'] = AgentConfigView(self)
        self.views['agent'].grid(row=0, column=1, sticky='nsew')
        self._init_standby_skills_on_launch()
        self.select_view('home')

    def _init_standby_skills_on_launch(self):
        import os, json
        if not os.path.exists('skills.json'):
            return
        try:
            with open('skills.json', 'r', encoding='utf-8') as f:
                skills_data = json.load(f)
        except Exception:
            return
        active_agent = skills_data.get('active_agent')
        agents = skills_data.get('agents', {})
        if not active_agent or active_agent not in agents:
            return
        agent_conf = agents[active_agent]
        md_dir = os.path.abspath(agent_conf.get('skill_md_dir', ''))
        scripts_dir = os.path.abspath(agent_conf.get('scripts_dir', ''))
        os.makedirs(md_dir, exist_ok=True)
        os.makedirs(scripts_dir, exist_ok=True)
        source_tools_dir = os.path.abspath('agent_tools')
        disabled_template_path = os.path.join(source_tools_dir, 'SKILL_DISABLED_TEMPLATE.md')
        if os.path.exists(disabled_template_path):
            with open(disabled_template_path, 'r', encoding='utf-8') as f:
                deactivated_content = f.read()
            with open(os.path.join(md_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
                f.write(deactivated_content)
        auth_file = os.path.join(scripts_dir, '.agent_auth.json')
        if os.path.exists(auth_file):
            os.remove(auth_file)

    def handle_connection_success(self, final_config: dict):
        import threading
        import tkinter.messagebox as messagebox
        self.conn_status_label.configure(text='正在初始化 Agent 与终端环境...', text_color='#F1C40F')

        def _setup_worker():
            import os, json, paramiko
            from network.pty_manager import StatefulPTYManager
            from network.agent_ipc import AgentIPCGateway
            from ui.agent_delegate import ZeroSyncAgentDelegate
            if getattr(self, 'agent_gateway', None):
                try:
                    self.agent_gateway.stop()
                except Exception:
                    pass
            if getattr(self, 'pty_manager', None):
                try:
                    self.pty_manager.stop()
                except Exception:
                    pass
            if getattr(self, 'agent_ssh', None):
                try:
                    self.agent_ssh.close()
                except Exception:
                    pass
            try:
                ssh_conf = final_config.get('ssh', {})
                self.agent_ssh = paramiko.SSHClient()
                self.agent_ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if ssh_conf.get('key_path'):
                    self.agent_ssh.connect(ssh_conf.get('hostname'), port=int(ssh_conf.get('port', 22)), username=ssh_conf.get('username'), key_filename=ssh_conf.get('key_path'), passphrase=ssh_conf.get('password'), timeout=10)
                else:
                    self.agent_ssh.connect(ssh_conf.get('hostname'), port=int(ssh_conf.get('port', 22)), username=ssh_conf.get('username'), password=ssh_conf.get('password'), timeout=10)
                self.pty_manager = StatefulPTYManager(self.agent_ssh)
                self.pty_manager.on_output_callback = self.views['workspace'].write_cmd_output
                docker_name = final_config.get('docker_name', '')
                if docker_name:
                    self.pty_manager.start(f'docker exec -it {docker_name} /bin/bash\r')
                else:
                    self.pty_manager.start(f"cd {final_config.get('remote_dir', '/')}\r")
                import time
                time.sleep(0.5)
                conda_hooks = [f"cd {final_config.get('remote_dir', '/')}", 'export PATH=$PATH:/usr/bin:/bin', 'eval "$(conda shell.bash hook 2> /dev/null)"', 'eval "$(/opt/conda/bin/conda shell.bash hook 2> /dev/null)"', 'eval "$(/media/miniconda3/condabin/conda shell.bash hook 2> /dev/null)"', 'clear']
                self.pty_manager.human_write('; '.join(conda_hooks) + '\r')
                self.views['workspace'].pty_manager = self.pty_manager
                agent_port = 50055
                if os.path.exists('skills.json'):
                    try:
                        with open('skills.json', 'r', encoding='utf-8') as f:
                            skills_data = json.load(f)
                            agent_port = int(skills_data.get('agent_port', 50055))
                    except Exception:
                        pass
                bridge = getattr(self, 'bridge', None)
                delegate = ZeroSyncAgentDelegate(bridge, self.pty_manager, self.views['workspace'], self.agent_ssh, final_config)
                self.agent_gateway = AgentIPCGateway(port=agent_port, delegate=delegate)
                self.agent_gateway.start()
                time.sleep(0.5)
                self.agent_token = self.agent_gateway.access_token
                self.after(0, _on_success)
            except Exception as e:
                self.after(0, lambda err=e: _on_error(err))

        def _on_error(error_msg):
            self.conn_status_label.configure(text='终端环境初始化失败', text_color='#E74C3C')
            self.views['workspace'].append_log(f'Agent engine failed to start: {error_msg}', 'ERROR')
            messagebox.showerror('连接初始化失败', f'与服务器建立终端安全连接时发生异常！\n\n原因：{error_msg}')

        def _on_success():
            self.is_connected = True
            self.active_config = final_config
            self.nav_workspace_btn.configure(state='normal', text='同步工作台', text_color=('gray10', 'gray90'))
            target_ip = final_config.get('ssh', {}).get('hostname', 'Unknown')
            self.conn_status_label.configure(text=f'🟢 已连接: {target_ip}', text_color='#2ECC71')
            self._auto_emit_agent_skills(final_config)
            self.select_view('workspace')
            self.views['workspace'].append_log('[UI] SSH tunnel and PTY terminal are ready.', 'INFO')
            self.views['workspace'].init_pty_terminal()
            if final_config.get('enable_agent', False):
                import tkinter.messagebox as messagebox
                messagebox.showinfo('智能体环境已就绪', 'ZeroSync 已经成功连接并更新了 Agent 工具链。\n\n如果您的智能体对话窗口已经打开，请执行【重新加载技能】的操作，以确保智能体获取最新的连接状态。')
        threading.Thread(target=_setup_worker, daemon=True).start()

    def _auto_emit_agent_skills(self, config: dict):
        import os
        import json
        import shutil
        if not os.path.exists('skills.json'):
            self.views['workspace'].append_log('skills.json not found, skipped agent injection.', 'WARNING')
            return
        try:
            with open('skills.json', 'r', encoding='utf-8') as f:
                skills_data = json.load(f)
        except Exception:
            self.views['workspace'].append_log('skills.json is empty or invalid, skipped agent injection.', 'WARNING')
            return
        active_agent = skills_data.get('active_agent')
        agent_port = skills_data.get('agent_port', '50052')
        agents = skills_data.get('agents', {})
        if not active_agent or active_agent not in agents:
            self.views['workspace'].append_log('No valid agent configured, skipped agent injection.', 'WARNING')
            return
        agent_conf = agents[active_agent]
        md_dir = os.path.abspath(agent_conf.get('skill_md_dir', ''))
        scripts_dir = os.path.abspath(agent_conf.get('scripts_dir', ''))
        os.makedirs(md_dir, exist_ok=True)
        os.makedirs(scripts_dir, exist_ok=True)
        source_tools_dir = os.path.abspath('agent_tools')
        if not config.get('enable_agent', False):
            disabled_template_path = os.path.join(source_tools_dir, 'SKILL_DISABLED_TEMPLATE.md')
            if os.path.exists(disabled_template_path):
                with open(disabled_template_path, 'r', encoding='utf-8') as f:
                    deactivated_content = f.read()
            else:
                deactivated_content = '---\nname: zerosync-copilot\ndescription: DISABLED. Ignore this skill.\n---\n# DISABLED'
            with open(os.path.join(md_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
                f.write(deactivated_content)
            auth_file = os.path.join(scripts_dir, '.agent_auth.json')
            if os.path.exists(auth_file):
                os.remove(auth_file)
            self.views['workspace'].append_log(f'Agent injection disabled by user. Deactivated skills deployed to {active_agent}.', 'WARNING')
            return
        source_tools_dir = os.path.abspath('agent_tools')
        template_path = os.path.join(source_tools_dir, 'SKILL_TEMPLATE.md')
        if os.path.exists(template_path):
            with open(template_path, 'r', encoding='utf-8') as f:
                template_content = f.read()
            hostname = config.get('ssh', {}).get('hostname', 'Local/Unknown')
            remote_dir = config.get('remote_dir', '/')
            docker_name = config.get('docker_name')
            docker_status = f'Yes (Container: {docker_name})' if docker_name else 'No (Native SSH)'
            skill_content = template_content.replace('{HOSTNAME}', hostname).replace('{REMOTE_DIR}', remote_dir).replace('{DOCKER_STATUS}', docker_status).replace('{SCRIPTS_DIR}', scripts_dir.replace('\\', '/'))
            with open(os.path.join(md_dir, 'SKILL.md'), 'w', encoding='utf-8') as f:
                f.write(skill_content)
        auth_data = {'endpoint': f'http://127.0.0.1:{agent_port}', 'token': getattr(self, 'agent_token', 'YOUR_RUNTIME_TOKEN'), 'workspace': config.get('remote_dir', '/')}
        with open(os.path.join(scripts_dir, '.agent_auth.json'), 'w', encoding='utf-8') as f:
            json.dump(auth_data, f)
        if os.path.exists(source_tools_dir):
            for file in os.listdir(source_tools_dir):
                if file.endswith('.py'):
                    shutil.copy(os.path.join(source_tools_dir, file), os.path.join(scripts_dir, file))
        self.views['workspace'].append_log(f'Agent skills successfully injected into {active_agent}!', 'INFO')

    def select_view(self, view_name: str):
        self.nav_home_btn.configure(fg_color='transparent')
        if self.is_connected:
            self.nav_workspace_btn.configure(fg_color='transparent')
        self.nav_config_btn.configure(fg_color='transparent')
        self.nav_agent_btn.configure(fg_color='transparent')
        if view_name == 'home':
            self.nav_home_btn.configure(fg_color=('gray75', 'gray25'))
            self.views['home'].refresh()
        elif view_name == 'workspace' and self.is_connected:
            self.nav_workspace_btn.configure(fg_color=('gray75', 'gray25'))
        elif view_name == 'config':
            self.nav_config_btn.configure(fg_color=('gray75', 'gray25'))
        elif view_name == 'agent':
            self.nav_agent_btn.configure(fg_color=('gray75', 'gray25'))
        self.views[view_name].tkraise()
if __name__ == '__main__':
    enable_dpi_awareness()
    app = ZeroSyncApp()
    app.mainloop()