"""Optional subtitle-free benchmark fixture; restores settings without stopping playback."""
from contextlib import contextmanager


def subtitle_state(rpc, player):
    value = rpc('Player.GetProperties', {'playerid':player,'properties':['subtitleenabled','currentsubtitle']})
    enabled = value.get('subtitleenabled')
    current = value.get('currentsubtitle')
    index = current.get('index') if isinstance(current,dict) else None
    if type(enabled) is not bool or (index is not None and (type(index) is not int or index < 0)):
        raise RuntimeError('Invalid subtitle state')
    if enabled and index is None:
        raise RuntimeError('Enabled subtitle lacks stream identity')
    return dict(enabled=enabled,index=index)


def same_player(rpc, player, item):
    videos = [entry for entry in rpc('Player.GetActivePlayers') if entry['type']=='video']
    if len(videos)!=1 or videos[0]['playerid']!=player:
        raise RuntimeError('Video player changed; refusing subtitle mutation')
    actual = rpc('Player.GetItem', {'playerid':player})['item']
    if (actual.get('id'),actual.get('type')) != item:
        raise RuntimeError('Movie identity changed; refusing subtitle mutation')


def wait_state(rpc, sleep, player, expected):
    for _ in range(20):
        actual = subtitle_state(rpc,player)
        if actual == expected:
            return actual
        sleep(.1)
    raise RuntimeError('Subtitle state did not reach expected value')


def validate_fixture(record, movie_id):
    if not isinstance(record,dict) or type(record.get('movie_id')) is not int or record['movie_id']!=movie_id or type(record.get('player_id')) is not int or record['player_id']<0:
        raise ValueError('Missing subtitle fixture identity')
    before = record.get('before',{})
    if not isinstance(before,dict) or type(before.get('enabled')) is not bool or (before.get('index') is not None and (type(before['index']) is not int or before['index']<0)) or (before['enabled'] and before.get('index') is None):
        raise ValueError('Invalid original subtitle fixture')
    disabled = dict(enabled=False,index=before.get('index'))
    if record.get('requested_enabled') is not False or record.get('disabled')!=disabled or record.get('disabled_at_end')!=disabled or record.get('restored')!=before:
        raise ValueError('Subtitle fixture disable/restore proof failed')


@contextmanager
def subtitles_off_fixture(requested, rpc, sleep, movie_id):
    if not requested:
        yield None
        return
    for _ in range(30):
        videos = [entry for entry in rpc('Player.GetActivePlayers') if entry['type']=='video']
        if len(videos)==1:
            break
        if len(videos)>1:
            raise RuntimeError('Ambiguous video player')
        sleep(1)
    else:
        raise RuntimeError('Video player unavailable for subtitle fixture')
    player = videos[0]['playerid']
    actual_item = rpc('Player.GetItem', {'playerid':player})['item']
    item = (actual_item.get('id'),actual_item.get('type'))
    if item != (movie_id,'movie'):
        raise RuntimeError('Unexpected playing movie')
    before = subtitle_state(rpc,player)
    record = dict(before=before,requested_enabled=False,player_id=player,movie_id=movie_id)
    try:
        same_player(rpc,player,item)
        rpc('Player.SetSubtitle', {'playerid':player,'subtitle':'off'})
        record['disabled'] = wait_state(rpc,sleep,player,dict(enabled=False,index=before['index']))
        yield record
        same_player(rpc,player,item)
        record['disabled_at_end'] = subtitle_state(rpc,player)
        if record['disabled_at_end'] != record['disabled']:
            raise RuntimeError('Subtitle fixture changed during measurement')
    finally:
        # Never stop, restart, force-kill or modify a different player.
        same_player(rpc,player,item)
        if before['index'] is not None:
            rpc('Player.SetSubtitle', {'playerid':player,'subtitle':before['index'],'enable':False})
        same_player(rpc,player,item)
        rpc('Player.SetSubtitle', {'playerid':player,'subtitle':'on' if before['enabled'] else 'off'})
        record['restored'] = wait_state(rpc,sleep,player,before)
