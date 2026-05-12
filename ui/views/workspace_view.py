import os
import re
import threading
import customtkinter as ctk
import tkinter.messagebox as messagebox
from ui.components.status_badge import StatusBadge
from ui.components.terminal_box import TerminalBox
from ui.components.terminal import TerminalWidget

class WorkspaceView(ctk.CTkFrame):

    def __init__(self, master, **kwargs):
        super().__init__(master, corner_radius=0, fg_color='transparent', **kwargs)
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)
        self.header_frame = ctk.CTkFrame(self, fg_color='transparent')
        self.header_frame.grid(row=0, column=0, sticky='ew', padx=20, pady=(20, 10))
        self.title_label = ctk.CTkLabel(self.header_frame, text='同步工作台', font=('Roboto', 24, 'bold'))
        self.title_label.pack(side='left')
        self.status_badge = StatusBadge(self.header_frame)
        self.status_badge.pack(side='right', pady=5)
        self.control_frame = ctk.CTkFrame(self)
        self.control_frame.grid(row=1, column=0, sticky='ew', padx=20, pady=5)
        self.control_frame.grid_columnconfigure((0, 1, 2), weight=1, uniform='btn_group')
        btn_height = 40
        btn_font = ('Roboto', 14, 'bold')
        lbl_font = ('Roboto', 13)
        lbl_color = 'gray60'
        self.sync_frame = ctk.CTkFrame(self.control_frame, fg_color='transparent')
        self.sync_frame.grid(row=0, column=0, padx=15, pady=15, sticky='nsew')
        ctk.CTkLabel(self.sync_frame, text='引擎主控', font=lbl_font, text_color=lbl_color).pack(pady=(0, 8))
        self.toggle_sync_btn = ctk.CTkButton(self.sync_frame, text='启动实时监听', font=btn_font, height=btn_height)
        self.toggle_sync_btn.pack(fill='x')
        self.init_frame = ctk.CTkFrame(self.control_frame, fg_color='transparent')
        self.init_frame.grid(row=0, column=1, padx=15, pady=15, sticky='nsew')
        ctk.CTkLabel(self.init_frame, text='云端覆盖', font=lbl_font, text_color=lbl_color).pack(pady=(0, 8))
        self.init_btn = ctk.CTkButton(self.init_frame, text='全量推送到服务器', font=btn_font, height=btn_height)
        self.init_btn.pack(fill='x')
        self.pull_frame = ctk.CTkFrame(self.control_frame, fg_color='transparent')
        self.pull_frame.grid(row=0, column=2, padx=15, pady=15, sticky='nsew')
        ctk.CTkLabel(self.pull_frame, text='本地恢复', font=lbl_font, text_color=lbl_color).pack(pady=(0, 8))
        self.pull_btn = ctk.CTkButton(self.pull_frame, text='挂起并从服务器拉取', font=btn_font, height=btn_height)
        self.pull_btn.pack(fill='x')
        self.tab_ctrl_frame = ctk.CTkFrame(self, fg_color='transparent', height=30)
        self.tab_ctrl_frame.grid(row=2, column=0, sticky='ew', padx=20, pady=(10, 0))
        self.tab_var = ctk.StringVar(value='交互式终端')
        self.tab_selector = ctk.CTkSegmentedButton(self.tab_ctrl_frame, values=['交互式终端', '运行日志'], variable=self.tab_var, command=self._switch_tab)
        self.tab_selector.pack(side='left')
        self.agent_status_label = ctk.CTkLabel(self.tab_ctrl_frame, text='🟢 Terminal: Idle', font=('Consolas', 12, 'bold'), text_color='#2ECC71')
        self.agent_status_label.pack(side='right', padx=10)
        self.panels_container = ctk.CTkFrame(self)
        self.panels_container.grid(row=3, column=0, sticky='nsew', padx=20, pady=(5, 20))
        self.panels_container.grid_rowconfigure(0, weight=1)
        self.panels_container.grid_columnconfigure(0, weight=1)
        self.log_panel = TerminalBox(self.panels_container)
        self.log_panel.grid(row=0, column=0, sticky='nsew')
        self.cmd_panel = ctk.CTkFrame(self.panels_container, fg_color='transparent')
        self.cmd_panel.grid_rowconfigure(0, weight=1)
        self.cmd_panel.grid_columnconfigure(0, weight=1)
        self.cmd_output = TerminalWidget(self.cmd_panel, on_input_callback=self._send_to_pty, on_resize_callback=self._on_pty_resize)
        self.cmd_output.grid(row=0, column=0, sticky='nsew', pady=(0, 5))
        self.agent_lock_frame = ctk.CTkFrame(self.cmd_panel, fg_color='transparent')
        self.agent_lock_frame.grid_columnconfigure(0, weight=1)
        self.agent_lock_label = ctk.CTkLabel(self.agent_lock_frame, text='Agent 助手正在执行操作，终端输入已锁定...', font=('Consolas', 14, 'bold'), text_color='#E74C3C', anchor='w')
        self.agent_lock_label.grid(row=0, column=0, sticky='w', padx=10)
        self.agent_interrupt_btn = ctk.CTkButton(self.agent_lock_frame, text='强制中断', font=('Roboto', 13, 'bold'), fg_color='#C0392B', hover_color='#A93226', width=140, command=self._send_ctrl_c)
        self.agent_interrupt_btn.grid(row=0, column=1, sticky='e', padx=10)
        self._switch_tab('交互式终端')
        self.is_running = False
        self.is_paused = False
        self.pty_manager = None
        self._output_queue = []
        self._output_lock = threading.Lock()
        self._update_scheduled = False

    def _switch_tab(self, value):
        if value == '交互式终端':
            self.log_panel.grid_remove()
            self.cmd_panel.grid(row=0, column=0, sticky='nsew')
        else:
            self.cmd_panel.grid_remove()
            self.log_panel.grid(row=0, column=0, sticky='nsew')

    def _send_ctrl_c(self):
        if self.pty_manager:
            self.pty_manager.send_interrupt()

    def append_log(self, text: str, level: str='INFO'):
        self.log_panel.append_log(text, level)
        if level.upper() in ['ERROR', 'CRITICAL']:

            def force_switch_to_log():
                target_tab = '运行日志'
                if self.tab_var.get() != target_tab:
                    self.tab_var.set(target_tab)
                    self._switch_tab(target_tab)
            self.after(0, force_switch_to_log)

    def _send_to_pty(self, data: str):
        if self.pty_manager:
            try:
                self.pty_manager.human_write(data)
            except Exception:
                pass

    def _on_pty_resize(self, columns, rows):
        if self.pty_manager and self.pty_manager.channel:
            try:
                self.pty_manager.channel.resize_pty(width=columns, height=rows)
            except Exception:
                pass

    def write_cmd_output(self, text: str):
        self.cmd_output.feed(text)

    def init_pty_terminal(self):
        config = self.master.active_config
        if not config:
            return
        docker_name = config.get('docker_name', '')
        if docker_name:
            self.write_cmd_output(f'检测到 Docker 环境: {docker_name}\n')
            self.write_cmd_output('后台 PTY 将自动为您注入: docker exec -it ...\n')
        else:
            self.write_cmd_output('原生 SSH PTY 环境就绪。\n')

    def set_agent_lock(self, locked: bool):
        if locked:
            self.agent_status_label.configure(text='🔴 Terminal: Agent Executing...', text_color='#E74C3C')
            self.agent_lock_frame.grid(row=1, column=0, sticky='ew')
        else:
            self.agent_status_label.configure(text='🟢 Terminal: Idle', text_color='#2ECC71')
            self.agent_lock_frame.grid_remove()