class ControlTower:
    def __init__(self,usage_ledger,evaluation_store,health):
        self.usage=usage_ledger; self.evals=evaluation_store; self.health=health
    def snapshot(self):
        events=self.usage.recent(1000)
        total=sum(e.get('total_tokens',0) for e in events)
        blocked=sum(1 for e in events if e.get('decision')=='BLOCK')
        success=sum(1 for e in events if e.get('status')=='success')
        ev=self.evals.recent(1000)
        avg=round(sum(x.get('overall',0) for x in ev)/len(ev),3) if ev else None
        by_model={}
        for e in events:
            k=f"{e.get('provider')}:{e.get('model')}"; by_model.setdefault(k,{'requests':0,'tokens':0}); by_model[k]['requests']+=1; by_model[k]['tokens']+=e.get('total_tokens',0)
        return {'requests':len(events),'successful_requests':success,'blocked_requests':blocked,'total_tokens':total,'evaluation_count':len(ev),'average_evaluation_score':avg,'by_model':by_model,'provider_health':self.health.snapshot()}
