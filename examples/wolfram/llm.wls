#!/usr/bin/env wolframscript
(* ============================================================
   llm.wls — unified, CLOUD-OPTIONAL LLM access for the Wolfram side.

   Goal: the same graph code / script / notebook runs WITHOUT Wolfram Cloud
   (using your own provider key or the local claude CLI), AND also runs when
   Wolfram Cloud / LLM Kit IS available. Nothing is hard-bound to the cloud.

   Use `ask[prompt]` inside LLMGraph EvaluationFunction nodes:
     Get["examples/wolfram/llm.wls"];
     g = LLMGraph[<|"a" -> <|"Input"->{"Topic"},
           "EvaluationFunction" -> Function[s, ask["haiku about " <> s["Topic"]]]|>|>];
     g[<|"Topic" -> "spring"|>]

   Backend resolution (preference via env LLMGRAPH_WL_BACKEND):
     auto (default) : first cloud-free that's available
                      -> deepseek key -> qwen key -> claude CLI -> cloud LLM Kit
     deepseek | qwen | claude | cloud : force one
   So: no cloud needed by default; set LLMGRAPH_WL_BACKEND=cloud (and sign in)
   to use Wolfram AI Access instead, with the exact same graph code.
   ============================================================ *)

bmpOnly[s_String] := StringDelete[s, Except[CharacterRange[0, 65535]]];
bmpOnly[x_] := x;
env[n_String] := With[{v = Environment[n]}, If[StringQ[v], v, $Failed]];

(* ---- cloud-free direct backends (your own key / local CLI) ---- *)
claudeExe = "C:\\Users\\hypergroups\\.local\\bin\\claude.exe";
askClaude[p_String] := bmpOnly @ StringTrim @ RunProcess[
  {claudeExe, "-p", "--output-format", "text"}, "StandardOutput", p];

httpChat[endpoint_, key_, model_, prompt_] := Module[{resp, body, parsed, t},
  If[! StringQ[key], Return[Failure["NoKey", <|"MessageTemplate" -> "missing key"|>]]];
  Do[
    resp = Quiet @ URLRead @ HTTPRequest[endpoint, <|
      "Method" -> "POST",
      "Headers" -> {"Authorization" -> "Bearer " <> key, "Content-Type" -> "application/json"},
      "Body" -> ExportString[<|"model" -> model, "messages" -> {
        <|"role" -> "system", "content" -> "Respond in plain text without emoji."|>,
        <|"role" -> "user", "content" -> prompt|>}|>, "RawJSON"]|>];
    If[Head[resp] === HTTPResponse && resp["StatusCode"] === 200, Break[]];
    Pause[1], {t, 3}];
  If[! (Head[resp] === HTTPResponse && resp["StatusCode"] === 200),
    Return[Failure["HTTP", <|"MessageTemplate" -> "request failed after retries"|>]]];
  body = StringReplace[bmpOnly[resp["Body"]], RegularExpression["\\\\u[dD][89a-fA-F][0-9a-fA-F]{2}"] -> ""];
  parsed = Quiet @ ImportString[body, "RawJSON"];
  If[! AssociationQ[parsed], Return[Failure["Parse", <||>]]];
  bmpOnly @ parsed["choices"][[1]]["message"]["content"]];

askQwen[p_String] := httpChat["https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
  env["DASHSCOPE_API_KEY"], "qwen-plus", p];
askDeepSeek[p_String] := httpChat["https://api.deepseek.com/chat/completions",
  env["DEEPSEEK_API_KEY"], "deepseek-chat", p];

(* ---- cloud path (Wolfram AI Access / LLM Kit), used only if chosen/available ---- *)
askCloud[p_String] := bmpOnly @ LLMSynthesize[p];
cloudAvailableQ[] := TrueQ[$CloudConnected];

(* ---- resolution: cloud-free first, cloud optional ---- *)
chooseBackend[] := Switch[env["LLMGRAPH_WL_BACKEND"],
  "deepseek", "deepseek",
  "qwen", "qwen",
  "claude" | "claude-cli", "claude",
  "cloud" | "llmkit", "cloud",
  _, Which[
    StringQ @ env["DEEPSEEK_API_KEY"], "deepseek",
    StringQ @ env["DASHSCOPE_API_KEY"], "qwen",
    FileExistsQ[claudeExe], "claude",
    cloudAvailableQ[], "cloud",
    True, "none"]];

$llmBackend = chooseBackend[];
ask[p_String] := Switch[$llmBackend,
  "deepseek", askDeepSeek[p],
  "qwen", askQwen[p],
  "claude", askClaude[p],
  "cloud", askCloud[p],
  _, Failure["NoBackend", <|"MessageTemplate" -> "no LLM backend available (set a key or LLMGRAPH_WL_BACKEND)"|>]];

Print["[llm] backend = ", $llmBackend, "  (Wolfram Cloud ", If[cloudAvailableQ[], "available", "absent"], ")"];
