import json
import os
import customtkinter as ctk
import tkinter.messagebox as messagebox
CONFIG_FILE = 'config.json'

class ConfigView(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=0, fg_color='transparent', **kwargs)
        self.grid_rowconfigure(1, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=3)
        self.title_label = ctk.CTkLabel(self, text='服务器与目录配置', font=('Roboto', 24, 'bold'))
        self.title_label.grid(row=0, column=0, columnspan=2, sticky='w', padx=20, pady=(20, 10))
        self.list_frame = ctk.CTkFrame(self)
        self.list_frame.grid(row=1, column=0, sticky='nsew', padx=(20, 10), pady=10)
        self.list_frame.grid_rowconfigure(1, weight=1)
        ctk.CTkLabel(self.list_frame, text='同步方案列表', font=('Roboto', 14, 'bold')).grid(row=0, column=0, pady=10)
        self.profile_listbox = ctk.CTkScrollableFrame(self.list_frame)
        self.profile_listbox.grid(row=1, column=0, sticky='nsew', padx=10, pady=(0, 10))
        self.add_btn = ctk.CTkButton(self.list_frame, text='➕ 新增配置', command=self._add_new_profile)
        self.add_btn.grid(row=2, column=0, sticky='ew', padx=10, pady=10)
        self.form_frame = ctk.CTkFrame(self)
        self.form_frame.grid(row=1, column=1, sticky='nsew', padx=(10, 20), pady=10)
        self.form_frame.grid_columnconfigure(1, weight=1)
        self.entries = {}
        fields = [('方案名称:', 'name', '如: 实验室 GPU-23'), ('本地目录:', 'local_dir', '如: D:/workspace/llm'), ('远端目标目录:', 'remote_dir', '要同步数据的存放路径'), ('服务端程序目录:', 'agent_dir', 'Server文件存放位置, 默认: ~/.zerosync'), ('Docker 容器名:', 'docker_name', '如不使用Docker请留空，例如: my_env'), ('服务器 IP:', 'hostname', '11.11.26.1'), ('端口:', 'port', '22'), ('用户名:', 'username', 'yyk06'), ('密码/私钥密码:', 'password', '登录密码或私钥保护密码'), ('私钥路径:', 'key_path', '如: C:/Users/Lenovo/.ssh/id_rsa (选填)'), ('gRPC 隧道端口:', 'grpc_port', '50051 (一般勿动)')]
        for i, (label_text, key, placeholder) in enumerate(fields):
            ctk.CTkLabel(self.form_frame, text=label_text, anchor='w').grid(row=i, column=0, padx=15, pady=(12, 0), sticky='w')
            entry = ctk.CTkEntry(self.form_frame, placeholder_text=placeholder)
            if key == 'password':
                entry.configure(show='*')
            entry.grid(row=i, column=1, padx=15, pady=(12, 0), sticky='ew')
            self.entries[key] = entry
        self.btn_frame = ctk.CTkFrame(self.form_frame, fg_color='transparent')
        self.btn_frame.grid(row=len(fields), column=0, columnspan=2, sticky='e', padx=15, pady=20)
        self.del_btn = ctk.CTkButton(self.btn_frame, text='删除', fg_color='#C0392B', hover_color='#A93226', width=40, command=self._delete_profile)
        self.del_btn.pack(side='left', padx=10)
        self.save_btn = ctk.CTkButton(self.btn_frame, text='保存配置', width=80, command=self._save_profile)
        self.save_btn.pack(side='left')
        self.config_data = {'profiles': [], 'active_profile': ''}
        self.current_profile_index = -1
        self.profile_buttons = []
        self._load_config()

    def _load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    self.config_data = json.load(f)
            except Exception:
                pass
        if not isinstance(self.config_data, dict):
            self.config_data = {}
        if 'profiles' not in self.config_data:
            self.config_data['profiles'] = []
        if 'active_profile' not in self.config_data:
            self.config_data['active_profile'] = ''
        self._refresh_listbox()

    def _refresh_listbox(self):
        for btn in self.profile_buttons:
            btn.destroy()
        self.profile_buttons.clear()
        profiles = self.config_data.get('profiles', [])
        for i, prof in enumerate(profiles):
            btn = ctk.CTkButton(self.profile_listbox, text=prof.get('name', f'Profile {i}'), fg_color='transparent', text_color=('gray10', 'gray90'), anchor='w', command=lambda idx=i: self._select_profile(idx))
            btn.pack(fill='x', pady=2)
            self.profile_buttons.append(btn)
        if profiles:
            self._select_profile(0)
        else:
            self._clear_form()

    def _select_profile(self, index: int):
        self.current_profile_index = index
        prof = self.config_data['profiles'][index]
        for i, btn in enumerate(self.profile_buttons):
            btn.configure(fg_color=('gray75', 'gray25') if i == index else 'transparent')
        self._clear_form()
        self.entries['name'].insert(0, prof.get('name', ''))
        self.entries['local_dir'].insert(0, prof.get('local_dir', ''))
        self.entries['remote_dir'].insert(0, prof.get('remote_dir', ''))
        self.entries['agent_dir'].insert(0, prof.get('agent_dir', '~/.zerosync'))
        self.entries['docker_name'].insert(0, prof.get('docker_name', ''))
        self.entries['grpc_port'].insert(0, str(prof.get('grpc_port', 50051)))
        ssh = prof.get('ssh', {})
        self.entries['hostname'].insert(0, ssh.get('hostname', ''))
        self.entries['port'].insert(0, str(ssh.get('port', 22)))
        self.entries['username'].insert(0, ssh.get('username', ''))
        self.entries['password'].insert(0, ssh.get('password', ''))
        self.entries['key_path'].insert(0, ssh.get('key_path', ''))

    def _clear_form(self):
        for entry in self.entries.values():
            entry.delete(0, 'end')

    def _add_new_profile(self):
        new_prof = {'name': '新建服务器配置', 'local_dir': '', 'remote_dir': '', 'agent_dir': '~/.zerosync', 'docker_name': '', 'grpc_port': 50051, 'ssh': {'hostname': '', 'port': 22, 'username': '', 'password': '', 'key_path': ''}}
        self.config_data['profiles'].append(new_prof)
        self._refresh_listbox()
        self._select_profile(len(self.config_data['profiles']) - 1)

    def _save_profile(self):
        if self.current_profile_index == -1:
            return
        name = self.entries['name'].get().strip()
        if not name:
            messagebox.showwarning('警告', '方案名称不能为空！')
            return
        prof = self.config_data['profiles'][self.current_profile_index]
        prof['name'] = name
        prof['local_dir'] = self.entries['local_dir'].get().strip()
        prof['remote_dir'] = self.entries['remote_dir'].get().strip()
        prof['agent_dir'] = self.entries['agent_dir'].get().strip() or '~/.zerosync'
        prof['docker_name'] = self.entries['docker_name'].get().strip()
        try:
            prof['grpc_port'] = int(self.entries['grpc_port'].get().strip() or 50051)
            port = int(self.entries['port'].get().strip() or 22)
        except ValueError:
            messagebox.showerror('错误', '端口必须是数字！')
            return
        prof['ssh'] = {'hostname': self.entries['hostname'].get().strip(), 'port': port, 'username': self.entries['username'].get().strip(), 'password': self.entries['password'].get().strip(), 'key_path': self.entries['key_path'].get().strip()}
        self.config_data['active_profile'] = name
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config_data, f, indent=4, ensure_ascii=False)
            messagebox.showinfo('成功', '配置保存成功！')
            self._refresh_listbox()
            self._select_profile(self.current_profile_index)
        except Exception as e:
            messagebox.showerror('保存失败', str(e))

    def _delete_profile(self):
        if self.current_profile_index == -1:
            return
        if messagebox.askyesno('确认删除', '确定要删除此服务器配置吗？'):
            del self.config_data['profiles'][self.current_profile_index]
            self.current_profile_index = -1
            self._save_profile()
            self._refresh_listbox()