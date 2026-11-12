$ErrorActionPreference='Stop'
$folder=Join-Path $env:RUNNER_TEMP 'vlogcraft-ffmpeg'
New-Item -ItemType Directory -Force $folder | Out-Null
$archive=Join-Path $folder 'ffmpeg.7z'
$url='https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-full.7z'
Invoke-WebRequest $url -OutFile $archive
Invoke-WebRequest ($url+'.sha256') -OutFile ($archive+'.sha256')
$expected=((Get-Content -Raw ($archive+'.sha256')).Trim() -split '\s+')[0]
$actual=(Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
if ($actual -ne $expected) { throw 'FFmpeg checksum verification failed' }
& 7z x $archive ("-o"+$folder) -y | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'FFmpeg extraction failed' }
$binary=Get-ChildItem -LiteralPath $folder -Filter ffmpeg.exe -Recurse | Select-Object -First 1
$binary.DirectoryName | Out-File -Append -FilePath $env:GITHUB_PATH -Encoding utf8
& $binary.FullName -version
