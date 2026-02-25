from djevops.config import SQLITE_DB_FILE

def get_litestream_config(backup_config):
    return {
        'dbs': [{
            'path': SQLITE_DB_FILE,
            'replica': backup_config
        }]
    }
