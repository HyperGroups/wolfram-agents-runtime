#!/usr/bin/env wolframscript
(* ============================================================
   deepseek_config.wls — NATIVE (mode B) DeepSeek in Wolfram's LLM framework.

   DeepSeek IS a registered Wolfram LLM service, so unlike Qwen it works
   through Wolfram's NATIVE plumbing WITHOUT Wolfram Cloud / LLM Kit:
   set DEEPSEEK_API_KEY and ConnectToService reads it (keyName
   "DEEPSEEK_API_KEY") and calls DeepSeek's own endpoint directly.

   This is the "registered provider, direct, cloud-free" path. For the
   cloud-OPTIONAL unified access used elsewhere (any provider, incl. Qwen, plus
   a cloud fallback), see examples/wolfram/llm.wls and its ask[].

   Usage:
     Get["examples/wolfram/deepseek_config.wls"];   (* sets $LLMEvaluator *)
     LLMSynthesize["write a haiku about spring"]     (* native, via DeepSeek *)
     g = LLMGraph[<|"a" -> "haiku about `Topic`"|>]; g[<|"Topic" -> "spring"|>]
   ============================================================ *)

$LLMEvaluator = LLMConfiguration[<|
  "Model" -> <|"Service" -> "DeepSeek", "Name" -> "deepseek-chat"|>
|>];

If[StringQ[Environment["DEEPSEEK_API_KEY"]],
  Print["[deepseek_config] native DeepSeek set as $LLMEvaluator (cloud-free)."],
  Print["[deepseek_config] WARNING: set DEEPSEEK_API_KEY in the environment."]];
