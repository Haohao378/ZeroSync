import sys
import ctypes
from ui.main_window import ZeroSyncApp
from ui.core_bridge import CoreBridge

def enable_dpi_awareness():
    if sys.platform == 'win32':
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass

def main():
    enable_dpi_awareness()
    app = ZeroSyncApp()

    def on_engine_ready():
        workspace_view.toggle_sync_btn.configure(state='normal', text='停止引擎', fg_color='#C0392B', hover_color='#A93226')

    def on_engine_stopped():

        def _reset_ui():
            workspace_view.is_running = False
            workspace_view.toggle_sync_btn.configure(state='normal', text='启动监听', fg_color=('#3a7ebf', '#1f538d'), hover_color=('#325882', '#14375e'))
        workspace_view.after(0, _reset_ui)

    def on_engine_reconnected():
        if app.active_config:
            app.views['workspace'].append_log('Silently rebuilding terminal environment...', 'WARN')
            workspace_view.after(0, lambda: app.handle_connection_success(app.active_config))
    bridge = CoreBridge(log_callback=app.views['workspace'].append_log, status_callback=app.views['workspace'].status_badge.set_status, ready_callback=on_engine_ready, stop_callback=on_engine_stopped, reconnect_callback=on_engine_reconnected)
    workspace_view = app.views['workspace']
    from utils.logger import register_ui_log_callback
    register_ui_log_callback(workspace_view.append_log)

    def ui_toggle_engine():
        if not workspace_view.is_running:
            workspace_view.is_running = True
            workspace_view.toggle_sync_btn.configure(state='disabled', text='正在打通底层隧道...', fg_color='#F39C12', hover_color='#D4AC0D')
            bridge.start_engine(app.active_config)
            if hasattr(app, 'agent_ssh') and app.agent_ssh:
                try:
                    transport = app.agent_ssh.get_transport()
                    if not transport or not transport.is_active():
                        workspace_view.append_log('Terminal connection lost. Rebuilding terminal environment...', 'WARN')
                        workspace_view.after(0, lambda: app.handle_connection_success(app.active_config))
                except Exception:
                    workspace_view.after(0, lambda: app.handle_connection_success(app.active_config))
            else:
                workspace_view.after(0, lambda: app.handle_connection_success(app.active_config))
        else:
            workspace_view.toggle_sync_btn.configure(state='disabled', text='正在停止...', fg_color='#F39C12', hover_color='#D4AC0D')
            bridge.stop_engine()
    workspace_view.toggle_sync_btn.configure(command=ui_toggle_engine)

    def ui_full_init():
        if not workspace_view.is_running:
            app.views['workspace'].append_log('Start the listener before executing a full sync.', 'ERROR')
            return
        bridge.trigger_full_init()
    workspace_view.init_btn.configure(command=ui_full_init)

    def ui_pause_for_pull():
        if bridge.is_running:
            bridge.pause_sync_for_pull()
        workspace_view.pull_btn.configure(state='disabled', text='拉取器运行中...')

        def on_downloader_closed():
            if bridge.is_running:
                bridge.resume_sync()
            workspace_view.pull_btn.configure(state='normal', text='服务器文件拉取')
        from ui.views.deploy_view import RemoteDownloaderDialog
        dialog = RemoteDownloaderDialog(master=app, config_dict=app.active_config, on_close_callback=on_downloader_closed)
    workspace_view.pull_btn.configure(text='服务器文件拉取', command=ui_pause_for_pull)

    def on_closing():
        if bridge.is_running:
            app.views['workspace'].append_log('Shutting down core engine...', 'INFO')
            bridge.stop_engine()
        if hasattr(app, '_init_standby_skills_on_launch'):
            try:
                app._init_standby_skills_on_launch()
                app.views['workspace'].append_log('Teardown: Agent credentials destroyed, reverted to standby mode.', 'INFO')
            except Exception as e:
                app.views['workspace'].append_log(f'Teardown error: {e}', 'ERROR')
        app.destroy()
        sys.exit(0)
    app.protocol('WM_DELETE_WINDOW', on_closing)
    app.mainloop()
if __name__ == '__main__':
    main()