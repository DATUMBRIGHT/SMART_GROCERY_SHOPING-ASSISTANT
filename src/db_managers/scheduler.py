from flask_apscheduler import APScheduler
from flask import Flask

class Scheduler:
    def __init__(self, app: Flask ):
        self.scheduler = APScheduler()
        self.app = app
        self.trigger = 'cron'
        self.hour = 0
        self.minute = 0
        self.second = 0
    
    def start(self, func, id, trigger='cron', **kwargs):
        self.scheduler.init_app(self.app)
        self.scheduler.add_job(id=id, func=func, trigger=trigger, **kwargs)
        self.scheduler.start()
