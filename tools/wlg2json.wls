#!/usr/bin/env wolframscript
(* ============================================================
   wlg2json.wls — transpile a Wolfram LLMGraph spec into our JSON IR.

   Usage:
     wolframscript -file tools/wlg2json.wls <input.wls> <output.json>

   The input .wls must DEFINE a symbol `spec` = the association you pass to
   LLMGraph, i.e. <|"name" -> "prompt with `slots`", ...|>. Reading the spec
   needs no LLM key (building an LLMGraph is lazy).

   Faithful (lossless) translation covers string-LLM nodes; the backtick slots
   carry over verbatim. Non-string nodes (Function / EvaluationFunction) cannot
   be losslessly extracted — they are emitted as a {"todo": ...} marker and
   reported, never silently dropped.
   ============================================================ *)

args = Rest[$ScriptCommandLine];
If[Length[args] < 2,
  Print["usage: wolframscript -file tools/wlg2json.wls <input.wls> <output.json>"];
  Quit[1]];
{inFile, outFile} = args[[1 ;; 2]];

spec =.;
Get[inFile];
If[! AssociationQ[spec],
  Print["error: source file must define `spec` as an association <|name -> prompt, ...|>"];
  Quit[1]];

(* Output (sink) nodes, via a lazily-built LLMGraph (no LLM call). *)
outputs = Quiet[Check[Information[LLMGraph[spec], "OutputNames"], Missing[]]];

notes = {};
jsonNodes = Association @ KeyValueMap[
  Function[{name, val},
    Which[
      StringQ[val],                       (* faithful: string-LLM node *)
        name -> val,
      AssociationQ[val] && StringQ[val["LLMFunction"]],
        name -> val["LLMFunction"],
      AssociationQ[val] && StringQ[val["Prompt"]],
        name -> val["Prompt"],
      True,                               (* not losslessly translatable *)
        AppendTo[notes, ToString[name] <> ": non-string node; not faithfully translatable"];
        name -> <|"todo" -> "non-LLM node; needs manual / AI-assisted migration"|>
    ]],
  spec];

ir = If[MissingQ[outputs],
  <|"nodes" -> jsonNodes|>,
  <|"nodes" -> jsonNodes, "output" -> outputs|>];

Export[outFile, ir, "RawJSON"];

Print["wrote ", outFile, "  (", Length[jsonNodes], " nodes, outputs = ", outputs, ")"];
If[notes =!= {},
  Print["NOT FAITHFUL — nodes needing attention:"];
  (Print["  - " <> #] &) /@ notes];
