#!/usr/bin/env wolframscript
(* ============================================================
   renga.wls — a real Wolfram LLMGraph, using Claude Code as the LLM backend.

   This is the "source of truth" config that runs in a wls script. Each node
   is evaluated by shelling out to the account-logged-in `claude` CLI
   (claude -p), so it needs NO Wolfram LLM-service key — it reuses the
   Claude Code login.

   It is the 1:1 counterpart of our runtime's IR file:
       examples/renga.json   (run on LangGraph via:  llmgraph run examples/renga.json --backend claude-cli)

   Translation mapping (Wolfram LLMGraph  ->  our JSON IR):
     node "haiku"    Input {Topic}  prompt "...about <Topic>."          ->  "haiku":    "generate a haiku about `Topic`."
     node "complete" Input {haiku}  prompt "...hokku <haiku>..."        ->  "complete": "add an extra stanza to the hokku `haiku` to make it a renga."
     graph input  <|"Topic"->...|>                                      ->  --input '{"Topic":"spring"}'
     output node  "complete" (sink)                                     ->  "output": ["complete"]
   ============================================================ *)

claudeExe = "C:\\Users\\hypergroups\\.local\\bin\\claude.exe";

(* The LLM backend: one headless Claude Code call, prompt fed on stdin. *)
askClaude[prompt_String] := StringTrim @ RunProcess[
  {claudeExe, "-p", "--output-format", "text"},
  "StandardOutput",
  prompt
];

(* The graph. Nodes are EvaluationFunctions that call Claude; dependencies are
   declared via "Input" (mirrors the backtick slots in the JSON IR). *)
renga = LLMGraph[<|
  "haiku" -> <|
    "Input" -> {"Topic"},
    (* EvaluationFunction receives ONE association keyed by the Input names. *)
    "EvaluationFunction" -> Function[a,
      askClaude["generate a haiku about " <> a["Topic"] <> "."]]
  |>,
  "complete" -> <|
    "Input" -> {"haiku"},
    "EvaluationFunction" -> Function[a,
      askClaude["add an extra stanza to the hokku\n" <> a["haiku"] <>
                "\nto make it a renga."]]
  |>
|>];

Print["=== Wolfram LLMGraph (claude code backend) ==="];
Print["Info: output nodes = ", Information[renga, "OutputNames"]];
Print[""];

result = renga[<|"Topic" -> "spring"|>];

Print["--- output node 'complete' ---"];
Print[result];
