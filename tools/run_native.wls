#!/usr/bin/env wolframscript
(* ============================================================
   run_native.wls — run an IR graph on Wolfram's NATIVE LLMGraph engine,
   so it can be cross-validated against our thin (LangGraph) runtime.

   Usage:
     wolframscript -file tools/run_native.wls <ir.json> <input.json> <out.json> [backend]

   Node handling:
     string prompt          -> EvaluationFunction calling the cloud-optional
                               ask[] (examples/wolfram/llm.wls). [backend] forces
                               LLMGRAPH_WL_BACKEND.
     {"wolfram": "<WL>"}     -> EvaluationFunction evaluating the WL natively in
                               this kernel (deps bound), deterministic.

   Emits structured JSON: per-node results (native values where JSON-able, else
   ToString) + structure + backend. Run from the project root.
   ============================================================ *)

args = Rest[$ScriptCommandLine];
If[Length[args] < 3,
  Print["usage: wolframscript -file tools/run_native.wls <ir.json> <input.json> <out.json> [backend]"];
  Quit[1]];
{irFile, inFile, outFile} = args[[1 ;; 3]];
If[Length[args] >= 4, SetEnvironment["LLMGRAPH_WL_BACKEND" -> args[[4]]]];

Get["examples/wolfram/llm.wls"];  (* defines ask[], $llmBackend *)

ir = Import[irFile, "RawJSON"];
nodes = ir["nodes"];

(* Map our backend names to Wolfram service names for LLMEvaluator *)
$backendToService = <|"openai" -> "OpenAI", "anthropic" -> "Anthropic", "deepseek" -> "DeepSeek"|>;

slots[t_String] := DeleteDuplicates @ StringCases[t, "`" ~~ s : Except["`"] .. ~~ "`" :> s];
render[t_String, a_] := StringReplace[t, "`" ~~ s : Except["`"] .. ~~ "`" :> ToString[Lookup[a, s, ""]]];
wdeps[code_String] := DeleteDuplicates @ StringCases[code,
  RegularExpression["deps\\[\\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\\s*\\]"] -> "$1"];
(* deps["X"] -> #X, so native can infer a ConditionalNode's TestFunction inputs *)
toSlots[code_String] := StringReplace[code,
  RegularExpression["deps\\[\\s*[\"']([A-Za-z_][A-Za-z0-9_]*)[\"']\\s*\\]"] -> "#$1"];
(* evaluate WL code with deps bound, no global state *)
evalWL[code_String, a_] := Quiet @ Check[ToExpression["Function[deps, " <> code <> "]"][a], $Failed];

(* Build LLMEvaluator for per-node model/backend, or None if not applicable *)
makeEvaluator[v_] := Module[{backend, model, service},
  backend = Lookup[v, "backend", None];
  model = Lookup[v, "model", None];
  If[backend === None && model === None, Return[None]];
  service = If[backend =!= None, Lookup[$backendToService, backend, None], None];
  If[service =!= None,
    (* Wolfram-native service: use LLMEvaluator *)
    LLMConfiguration[<|"Model" -> {service, If[model =!= None, model, Automatic]}|>],
    None]];

makeNode[name_, v_] := Which[
  StringQ[v],
    <|"Input" -> slots[v], "EvaluationFunction" -> Function[a, ask[render[v, a]]]|>,
  AssociationQ[v] && KeyExistsQ[v, "test"] && StringQ[v["wolfram"]],  (* ConditionalNode *)
    With[{code = v["wolfram"], in = Lookup[v, "input", wdeps[v["wolfram"]]],
          tin = Lookup[v, "test_input", wdeps[v["test"]]],
          tfun = ToExpression["Function[TrueQ[" <> toSlots[v["test"]] <> "]]"]},
      <|"Input" -> in, "EvaluationFunction" -> Function[a, evalWL[code, a]],
        "InputTestFunction" -> tin, "TestFunction" -> tfun|>],
  AssociationQ[v] && StringQ[v["wolfram"]],
    With[{code = v["wolfram"], in = Lookup[v, "input", wdeps[v["wolfram"]]]},
      <|"Input" -> in, "EvaluationFunction" -> Function[a, evalWL[code, a]]|>],
  AssociationQ[v] && StringQ[v["prompt"]],
    With[{ev = makeEvaluator[v]},
      If[ev =!= None,
        (* Per-node model/backend with Wolfram-native service *)
        <|"LLMFunction" -> v["prompt"], "LLMEvaluator" -> ev|>,
        (* Fallback: use ask[] with rendered prompt *)
        <|"Input" -> slots[v["prompt"]], "EvaluationFunction" -> Function[a, ask[render[v["prompt"], a]]]|>]],
  True,
    (Print["error: unsupported node ", name]; Quit[1])];

spec = Association @ KeyValueMap[Function[{name, v}, name -> makeNode[name, v]], nodes];

g = LLMGraph[spec];
input = If[FileExistsQ[inFile], Import[inFile, "RawJSON"], <||>];
res = g[input, All];

safeJSON[v_] := If[FailureQ[Quiet[ExportString[v, "RawJSON"]]], ToString[v], v];

out = <|
  "results" -> Map[safeJSON, res],
  "outputs" -> Information[g, "OutputNames"],
  "nodes" -> Keys[nodes],
  "edges" -> (EdgeList[Information[g, "Graph"]] /. DirectedEdge[a_, b_] :> {ToString[a], ToString[b]}),
  "backend" -> $llmBackend
|>;

If[FailureQ[Quiet[Export[outFile, out, "RawJSON"]]],
  Export[outFile, MapAt[Map[ToString], out, {"results"}], "RawJSON"]];
Print["[run_native] backend=", $llmBackend, " wrote ", outFile];
