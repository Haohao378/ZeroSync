import os
import json
import customtkinter as ctk
import tkinter.messagebox as messagebox
SKILLS_FILE = 'skills.json'

class AgentConfigView(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=0, fg_color='transparent', **kwargs)
        self.skills_data = {'active_agent': '', 'agent_port': '50052', 'agents': {}}
        self._load_config()
        self.grid_columnconfigure(0, weight=1)
        self.title_label = ctk.CTkLabel(self, text='智能体助手', font=('Roboto', 24, 'bold'))
        self.title_label.grid(row=0, column=0, sticky='w', padx=20, pady=(20, 10))
        self.desc_label = ctk.CTkLabel(self, text='在此配置您的外部 AI Agent (如 Gemini, Cursor, Claude Code等) 接入路径。\n当连接服务器并允许注入时，系统会自动将环境上下文和通信工具发送至目标目录。', text_color='gray', justify='left')
        self.desc_label.grid(row=1, column=0, sticky='w', padx=20, pady=(0, 20))
        self.card_active = ctk.CTkFrame(self, corner_radius=10)
        self.card_active.grid(row=2, column=0, sticky='ew', padx=20, pady=10)
        self.card_active.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.card_active, text='API 端口设置:', font=('Roboto', 13, 'bold')).grid(row=0, column=0, sticky='w', padx=20, pady=(20, 10))
        self.port_entry = ctk.CTkEntry(self.card_active, width=150)
        self.port_entry.grid(row=0, column=1, sticky='w', padx=10, pady=(20, 10))
        ctk.CTkLabel(self.card_active, text='当前目标智能体:', font=('Roboto', 13, 'bold')).grid(row=1, column=0, sticky='w', padx=20, pady=(10, 20))
        self.agent_var = ctk.StringVar()
        self.agent_menu = ctk.CTkOptionMenu(self.card_active, variable=self.agent_var, values=[])
        self.agent_menu.grid(row=1, column=1, sticky='w', padx=10, pady=(10, 20))
        self.apply_btn = ctk.CTkButton(self.card_active, text='应用当前配置', font=('Roboto', 13, 'bold'), fg_color='#27AE60', hover_color='#1E8449', command=self._apply_config)
        self.apply_btn.grid(row=1, column=2, sticky='e', padx=20, pady=10)
        self.card_add = ctk.CTkFrame(self, corner_radius=10)
        self.card_add.grid(row=3, column=0, sticky='ew', padx=20, pady=20)
        self.card_add.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(self.card_add, text='➕ 添加新智能体支持', font=('Roboto', 15, 'bold'), text_color='#8E44AD').grid(row=0, column=0, columnspan=2, sticky='w', padx=20, pady=(15, 10))
        ctk.CTkLabel(self.card_add, text='智能体名称:').grid(row=1, column=0, sticky='e', padx=10, pady=5)
        self.new_name_entry = ctk.CTkEntry(self.card_add, placeholder_text='例如: Claude Code')
        self.new_name_entry.grid(row=1, column=1, sticky='ew', padx=10, pady=5)
        ctk.CTkLabel(self.card_add, text='SKILL.md 目录:').grid(row=2, column=0, sticky='e', padx=10, pady=5)
        self.new_md_entry = ctk.CTkEntry(self.card_add, placeholder_text='例如: .claude/rules')
        self.new_md_entry.grid(row=2, column=1, sticky='ew', padx=10, pady=5)
        ctk.CTkLabel(self.card_add, text='工具脚本存放目录:').grid(row=3, column=0, sticky='e', padx=10, pady=5)
        self.new_scripts_entry = ctk.CTkEntry(self.card_add, placeholder_text='例如: agent_scripts')
        self.new_scripts_entry.grid(row=3, column=1, sticky='ew', padx=10, pady=5)
        self.add_btn = ctk.CTkButton(self.card_add, text='保存智能体配置', fg_color='#2980B9', hover_color='#1A5276', command=self._add_agent)
        self.add_btn.grid(row=4, column=0, columnspan=2, pady=(15, 20))
        self._refresh_ui()

    def _load_config(self):
        if os.path.exists(SKILLS_FILE):
            try:
                with open(SKILLS_FILE, 'r', encoding='utf-8') as f:
                    self.skills_data = json.load(f)
            except Exception:
                pass
        if 'agents' not in self.skills_data:
            self.skills_data['agents'] = {}

    def _save_config(self):
        with open(SKILLS_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.skills_data, f, indent=4, ensure_ascii=False)

    def _refresh_ui(self):
        self.port_entry.delete(0, 'end')
        self.port_entry.insert(0, self.skills_data.get('agent_port', '50052'))
        agent_names = list(self.skills_data.get('agents', {}).keys())
        if agent_names:
            self.agent_menu.configure(values=agent_names)
            active = self.skills_data.get('active_agent')
            if active in agent_names:
                self.agent_var.set(active)
            else:
                self.agent_var.set(agent_names[0])
        else:
            self.agent_menu.configure(values=['未配置'])
            self.agent_var.set('未配置')

    def _apply_config(self):
        self.skills_data['agent_port'] = self.port_entry.get().strip()
        self.skills_data['active_agent'] = self.agent_var.get()
        self._save_config()
        messagebox.showinfo('成功', '配置已生效！下次连接服务器时将自动使用此配置注入。')

    def _add_agent(self):
        name = self.new_name_entry.get().strip()
        md_dir = self.new_md_entry.get().strip()
        scripts_dir = self.new_scripts_entry.get().strip()
        if not name or not md_dir or (not scripts_dir):
            messagebox.showwarning('提示', '所有字段都必须填写！')
            return
        self.skills_data['agents'][name] = {'skill_md_dir': md_dir, 'scripts_dir': scripts_dir}
        self.skills_data['active_agent'] = name
        self._save_config()
        self._refresh_ui()
        self.new_name_entry.delete(0, 'end')
        self.new_md_entry.delete(0, 'end')
        self.new_scripts_entry.delete(0, 'end')
        messagebox.showinfo('成功', f'已成功添加并激活智能体: {name}')