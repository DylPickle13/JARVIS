"""Synthetic healthy observations. Never contacts phones."""
import readiness
from camera_config import ROLES,CONFIG_ID


def healthy():
    return {'ok':True,'config_id':CONFIG_ID,'checked_at':readiness.now(),
            'phones':{r:readiness.assess({'battery_percent':90,'free_bytes':10*1024**3,'external_power':True,'battery_temperature_c':30}) for r in ROLES},
            'collection_storage':{'ok':True,'free_bytes':20*1024**3}}
