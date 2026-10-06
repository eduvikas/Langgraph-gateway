from typing import TypedDict, Any
class GatewayState(TypedDict, total=False):
    request_id:str; session_id:str; application_id:str; user_id:str; prompt:str; authorization:str
    roles:set[str]; authenticated:bool; decision:str; block_reason:str
    selected_provider:str; selected_model:str; route_reason:str; route_score:float; history:list[dict[str,Any]]; response:str
    input_tokens:int; output_tokens:int; total_tokens:int; cache_hit:bool; estimated_cost_usd:float
    request_count:int; rate_remaining:int; data_classification:str; security_findings:list[dict[str,Any]]; security_reason:str
    evaluation:dict[str,Any]
