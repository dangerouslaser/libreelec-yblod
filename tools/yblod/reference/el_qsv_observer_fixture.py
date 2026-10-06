"""Persist original subtitle state before mutation; retain normal strict fixture."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import signal
import observe_subtitle_fixture as base


def interrupted(*unused):
    signal.signal(signal.SIGTERM,signal.SIG_IGN)
    signal.signal(signal.SIGINT,signal.SIG_IGN)
    raise RuntimeError('Owned observer interrupted; restore subtitle fixture')


def write_record(path,record):
    temporary=path.with_name(path.name+'.publishing')
    fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:
        json.dump(record,stream);stream.flush();os.fsync(stream.fileno())
    if path.is_symlink():raise RuntimeError('Subtitle recovery path became symlink')
    os.replace(temporary,path)


@contextmanager
def subtitles_off_fixture(requested,rpc,sleep,movie_id):
    path=Path(os.environ['YB_EL_SUBTITLE_RECOVERY'])
    if not path.is_absolute() or path.parent.resolve()!=path.parent or path.exists() or path.is_symlink():
        raise RuntimeError('Fresh private subtitle recovery record required')
    original=base.subtitle_state;snapshot=None;record=None
    def saved_state(api,player):
        nonlocal snapshot
        state=original(api,player)
        if snapshot is None:
            snapshot=dict(movie_id=movie_id,player_id=player,before=state,restored=False)
            write_record(path,snapshot)
        return state
    base.subtitle_state=saved_state
    try:
        with base.subtitles_off_fixture(requested,rpc,sleep,movie_id) as record:
            yield record
    finally:
        base.subtitle_state=original
        if snapshot is not None and record is not None and record.get('restored')==snapshot['before']:
            snapshot['restored']=True;write_record(path,snapshot)


def recover(path,rpc,sleep,movie_id):
    record=json.loads(path.read_text())
    if type(record.get('movie_id')) is not int or record['movie_id']!=movie_id or type(record.get('player_id')) is not int:
        raise RuntimeError('Unknown subtitle recovery ownership')
    if record.get('restored') is True:return
    state=record['before'];player=record['player_id']
    if not isinstance(state,dict) or set(state)!={'enabled','index'} or type(state['enabled']) is not bool or (state['index'] is not None and (type(state['index']) is not int or state['index']<0)) or (state['enabled'] and state['index'] is None):
        raise RuntimeError('Invalid original subtitle state')
    item=(movie_id,'movie');base.same_player(rpc,player,item)
    if state['index'] is not None:rpc('Player.SetSubtitle',{'playerid':player,'subtitle':state['index'],'enable':False})
    base.same_player(rpc,player,item)
    rpc('Player.SetSubtitle',{'playerid':player,'subtitle':'on' if state['enabled'] else 'off'})
    base.wait_state(rpc,sleep,player,state)
    record['restored']=True;write_record(path,record)
