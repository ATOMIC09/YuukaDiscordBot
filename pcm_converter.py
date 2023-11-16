'''import wave

# open PCM file for reading
with open('audio/output.pcm', 'rb') as pcmfile:
    pcmdata = pcmfile.read()

# set WAV file parameters
nchannels = 1
sampwidth = 2
framerate = 48000
nframes = len(pcmdata) // sampwidth

# create WAV file and write PCM data
with wave.open('audio/audio.wav', 'wb') as wavfile:
    wavfile.setparams((nchannels, sampwidth, framerate, nframes, 'NONE', 'NONE'))
    wavfile.writeframes(pcmdata)
'''

import wave

# Open a file in write-only mode
with wave.open('test.wav', 'w') as wf:
    # Set the parameters for the output file
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(44100)

    # Write some data to the file
    data = b'\x00\x00\x00\x00\x7f\xff\x7f\xff\x00\x00\x00\x00\x80\x00\x80\x00'
    wf.writeframes(data)