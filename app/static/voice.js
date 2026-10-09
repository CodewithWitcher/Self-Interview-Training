// Recording and reading aloud on the question page (F14, F15). The page works without it.
(function () {
  "use strict";

  var tools = document.getElementById("voice-tools");
  if (!tools) return;
  var status = document.getElementById("voice-status");
  var answer = document.getElementById("answer");
  var recordButton = document.getElementById("record-button");
  var speakButton = document.getElementById("speak-button");
  var MAX_MS = 5 * 60 * 1000;

  function say(message) {
    status.textContent = message;
  }

  // Recording

  var canRecord = !!(window.MediaRecorder && navigator.mediaDevices && navigator.mediaDevices.getUserMedia);
  var recorder = null;
  var chunks = [];
  var stopTimer = null;
  var stream = null;

  function mimeType() {
    if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported("audio/webm;codecs=opus")) {
      return "audio/webm;codecs=opus";
    }
    return "audio/mp4";
  }

  function setRecording(on) {
    recordButton.textContent = on ? "Stop recording" : "Record answer";
    recordButton.setAttribute("aria-pressed", on ? "true" : "false");
  }

  function upload(blob) {
    say("Transcribing...");
    recordButton.disabled = true;
    var form = new FormData();
    var ext = blob.type.indexOf("mp4") >= 0 ? "m4a" : "webm";
    form.append("audio", blob, "answer." + ext);
    fetch(tools.getAttribute("data-audio-url"), { method: "POST", body: form, credentials: "same-origin" })
      .then(function (response) {
        return response.json().catch(function () {
          return { error: "The recording could not be transcribed. Type your answer instead." };
        });
      })
      .then(function (data) {
        if (data.text) {
          answer.value = answer.value.trim() ? answer.value.trim() + " " + data.text : data.text;
          answer.dispatchEvent(new Event("input"));
          answer.focus();
          say("Transcript added to the answer box. Check it, then submit.");
        } else {
          say(data.error || "The recording could not be transcribed. Type your answer instead.");
        }
      })
      .catch(function () {
        say("The app could not be reached. Type your answer instead.");
      })
      .then(function () {
        recordButton.disabled = false;
      });
  }

  function stop() {
    if (recorder && recorder.state !== "inactive") recorder.stop();
  }

  function start() {
    navigator.mediaDevices.getUserMedia({ audio: true }).then(function (s) {
      stream = s;
      chunks = [];
      try {
        recorder = new MediaRecorder(stream, { mimeType: mimeType() });
      } catch (e) {
        recorder = new MediaRecorder(stream);
      }
      recorder.ondataavailable = function (event) {
        if (event.data && event.data.size) chunks.push(event.data);
      };
      recorder.onstop = function () {
        window.clearTimeout(stopTimer);
        stream.getTracks().forEach(function (track) { track.stop(); });
        setRecording(false);
        var blob = new Blob(chunks, { type: recorder.mimeType || mimeType() });
        chunks = [];
        upload(blob);
      };
      recorder.start();
      setRecording(true);
      say("Recording. Press Stop recording when you are done. Recording stops by itself after 5 minutes.");
      stopTimer = window.setTimeout(stop, MAX_MS);
    }).catch(function (error) {
      if (error && (error.name === "NotAllowedError" || error.name === "SecurityError")) {
        say("Microphone access was denied. Allow the microphone for this page in the browser and system settings, or type your answer.");
      } else if (error && error.name === "NotFoundError") {
        say("No microphone was found. Type your answer instead.");
      } else {
        say("Recording could not start. Check that the browser may use the microphone, or type your answer.");
      }
    });
  }

  if (canRecord && recordButton && answer) {
    recordButton.hidden = false;
    recordButton.addEventListener("click", function () {
      if (recorder && recorder.state === "recording") stop();
      else start();
    });
  }

  // Reading aloud, with a voice installed on this computer only.

  function localVoice() {
    if (!window.speechSynthesis) return null;
    var voices = window.speechSynthesis.getVoices();
    for (var i = 0; i < voices.length; i++) {
      if (voices[i].localService && voices[i].lang && voices[i].lang.toLowerCase().indexOf("en") === 0) {
        return voices[i];
      }
    }
    return null;
  }

  function offerSpeech() {
    if (speakButton && localVoice()) speakButton.hidden = false;
  }

  if (window.speechSynthesis && speakButton) {
    offerSpeech();
    window.speechSynthesis.addEventListener("voiceschanged", offerSpeech);
    speakButton.addEventListener("click", function () {
      var voice = localVoice();
      if (!voice) return;
      window.speechSynthesis.cancel();
      var utterance = new SpeechSynthesisUtterance(tools.getAttribute("data-prompt"));
      utterance.voice = voice;
      utterance.lang = voice.lang;
      window.speechSynthesis.speak(utterance);
    });
  }
})();
