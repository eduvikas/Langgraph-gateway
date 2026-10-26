from typing import TypedDict, Any
class GatewayState(TypedDict, total=False):
    request_id:str; session_id:str; application_id:str; user_id:str; prompt:str; authorization:str
    roles:set[str]; authenticated:bool; decision:str; block_reason:str
    selected_provider:str; selected_model:str; failed_models:list[str]; budget:dict; cache_key:str; cache_entry:dict; cache_skip:str; cost_usd:float; baseline_cost_usd:float; avoided_cost_usd:float; tokens_avoided:int; billable:bool; priced:bool; route_reason:str; route_score:float; routing_selected_provider:str; routing_selected_model:str; preflight_estimated_cost_usd:float; final_budget_reservation_id:str; budget_reservation_id:str; history:list[dict[str,Any]]; response:str
    input_tokens:int; output_tokens:int; total_tokens:int; cache_hit:bool; estimated_cost_usd:float
    request_count:int; rate_remaining:int; data_classification:str; routing_metadata:dict[str,Any]; task_type:str; routing_priority:str; routing_reason:str; routing_candidates:list[dict[str,Any]]; estimated_complexity:str; required_capabilities:list[str]; security_findings:list[dict[str,Any]]; security_reason:str
    evaluation:dict[str,Any]
