$ErrorActionPreference='Stop'
$folder=Join-Path $env:RUNNER_TEMP 'vlogcraft-ffmpeg'
New-Item -ItemType Directory -Force $folder | Out-Null
$archive=Join-Path $folder 'ffmpeg.7z'
$url='https://github.com/GyanD/codexffmpeg/releases/download/9.0.2/ffmpeg-9.0.2-full_build.7z'
$expected='f0e46253c70dfe902bac915dfb4224f0cf1b7c6eeab9da2ccc9a5581f9a71b13'
Invoke-WebRequest $url -OutFile $archive
$actual=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'FFmpeg checksum verification failed' }
& 7z x $archive ("-o"+$folder) -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg extraction failed' }
$binary=Get-ChildItem -LiteralPath $folder -Filter ffmpeg.exe -Recurse | Select-Object -First 1
$binary.DirectoryName | Out-File -Append -FilePath $env:GITHUB_PATH -Encoding utf8
& $binary.FullName -version
