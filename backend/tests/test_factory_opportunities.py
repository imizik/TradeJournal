"""Offline opportunity pilot: causal packets, frozen choices and hidden outcomes."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from datetime import date
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import factory_opportunities as op
from tests.test_factory import bar
from app.engine.factory_data import Series, Split


def spec():
    return op.search.rules.parse_spec({'family':'opening_range_breakout',
        'params':{'range_minutes':15},'exits':{'target_r':2,'max_minutes':60}})


def test_packet_does_not_reveal_next_open_fill_or_outcome_and_is_prefix_stable():
    day=date(2024,2,5)
    bars=[bar(day,m,100,101,99,100) for m in (570,575,580,585)]
    signal=SimpleNamespace(signal_index=3,signal_time=bars[3].time,ticker='TEST',side=1,
        stop=99,features={'day_move':1,'trend':0,'missing':float('nan')},entry_price=999,r=888)
    prefix=Series.build('TEST',bars,5)
    full=Series.build('TEST',bars+[bar(day,590,180,200,1,10)],5)
    a=op.packet(spec(),signal,prefix);b=op.packet(spec(),signal,full)
    assert a==b and a['entry_reference']==100 and a['target_reference']==102
    text=json.dumps(a)
    assert 'entry_price' not in text and '888' not in text and '999' not in text
    assert all(row['end']<=a['simulated_as_of'] for row in a['candles'])
    assert a['features']['missing'] is None
    assert a['option_eligibility']['available'] is False


def test_packet_restores_future_split_basis():
    day=date(2024,2,5)
    series=Series.build('TEST',[bar(day,570,10,10.1,9.9,10)],5)
    series.splits=[Split(date(2024,2,9),10)]
    signal=SimpleNamespace(signal_index=0,signal_time=series.time[0],ticker='TEST',side=1,
                           stop=9,features={})
    card=op.packet(spec(),signal,series)
    assert card['entry_reference']==100 and card['stop']==90
    assert card['candles'][0]['close']==100


def card(i,day='2024-02-05',ticker='TEST',family='one'):
    return {'id':str(i),'simulated_as_of':day+'T10:00:00-05:00',
            'candidate':{'spec_id':family,'ticker':ticker,'side':1,'signal_time':str(i)},
            'features':{'day_move':1,'trend':1}}


def test_balancing_is_stable_and_respects_day_ticker_quotas():
    cards=[card(i,ticker='T'+str(i%5),family='F'+str(i%3)) for i in range(60)]
    a=op.balanced(cards);b=op.balanced(list(reversed(cards)))
    assert a==b and len(a)<=op.MAX_PER_DAY
    from collections import Counter
    assert max(Counter(c['candidate']['ticker'] for c in a).values())<=op.MAX_PER_TICKER_DAY


def frozen(tmp_path):
    cards=[card(i) for i in range(3)]
    private={'nonce':'not-in-public','outcomes':{'0':{'resolved':True,'r':-1},
             '1':{'resolved':True,'r':2},'2':{'resolved':False,'r':None}}}
    public={'cards':cards,'sealed_outcomes_sha256':op.digest(private)}
    op.atomic(tmp_path/'operator-private/outcomes.json',private)
    op.atomic(tmp_path/'public/packets.json',public)
    return public


def choices(tmp_path,rows):
    p=tmp_path/'choices.json';p.write_text(json.dumps(rows));return p


def test_choices_are_immutable_idempotent_and_unknown_ids_refused(tmp_path):
    frozen(tmp_path)
    data=[{'id':'0','decision':'skip','reason':'fixture reason'}]
    assert op.decide(tmp_path,choices(tmp_path,data))==1
    assert op.decide(tmp_path,choices(tmp_path,data))==0
    with pytest.raises(ValueError,match='conflicts'):
        op.decide(tmp_path,choices(tmp_path,[{**data[0],'decision':'take'}]))
    with pytest.raises(ValueError,match='Unknown'):
        op.decide(tmp_path,choices(tmp_path,[{**data[0],'id':'unknown'}]))
    with pytest.raises(ValueError,match='Complete'):
        op.score(tmp_path)


def test_sealed_score_only_after_complete_choices_and_preserves_unresolved(tmp_path):
    frozen(tmp_path)
    op.decide(tmp_path,choices(tmp_path,[{'id':str(i),'decision':'take' if i else 'skip','reason':'fixture reason'} for i in range(3)]))
    result=op.score(tmp_path)
    assert result['jo_take']=={'selected':2,'resolved':1,'total_r':2,'mean_r':2}
    assert result['take_all']['total_r']==1
    assert result['fixed_context_filter']['selected']==3
    private=json.loads((tmp_path/'operator-private/outcomes.json').read_text());private['outcomes']['0']['r']=999
    op.atomic(tmp_path/'operator-private/outcomes.json',private)
    with pytest.raises(ValueError,match='seal'):op.score(tmp_path)


def test_gate_rejects_invalid_geometry_without_consulting_outcomes():
    day=date(2024,2,5);series=Series.build('TEST',[bar(day,570,100,101,99,100)],5)
    signal=SimpleNamespace(signal_index=0,signal_time=series.time[0],ticker='TEST',side=1,stop=101,features={})
    assert op.packet(spec(),signal,series) is None
