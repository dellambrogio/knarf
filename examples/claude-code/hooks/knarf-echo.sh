#!/usr/bin/env bash
# knarf voice traffic in the terminal: PreToolUse on speak (text shows before it is said), PostToolUse on listen.
jq -c '
  def txt: if type == "string" then .
    elif type == "array" then map(if type == "object" then (.text // "") else tostring end) | join(" ")
    elif type == "object" then (.text // .content // .transcript // tostring) | (if type == "string" then . else tostring end)
    else tostring end;
  if (.tool_name | endswith("__speak")) then {systemMessage: ("🔊 Claude: " + (.tool_input.text // ""))}
  elif (.tool_name | endswith("__listen")) then {systemMessage: ("🎤 You: " + (.tool_response | txt))}
  else empty end'
