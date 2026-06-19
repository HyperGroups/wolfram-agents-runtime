#!/usr/bin/env wolframscript
(* ============================================================
   renga_native.wls — the CANONICAL "knowledge" form of the graph.

   `spec` is exactly the association you pass to LLMGraph: node name -> prompt,
   with backtick slots. This is the portable knowledge. The transpiler
   tools/wlg2json.wls reads `spec`, emits our JSON IR, and the runtime runs it.

   Building `graph` is lazy (no LLM key needed) and just proves `spec` is a
   valid LLMGraph. This is the lossless-migration subset: string-LLM nodes.
   ============================================================ *)

spec = <|
  "haiku" -> "generate a haiku about `Topic`.",
  "complete" -> "add an extra stanza to the hokku `haiku` to make it a renga."
|>;

graph = LLMGraph[spec];
