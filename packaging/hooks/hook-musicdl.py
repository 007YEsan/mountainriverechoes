from PyInstaller.utils.hooks import collect_data_files, collect_submodules

# musicdl 的音源客户端靠注册表动态发现, 且自带 .wvd(Widevine 设备文件)等数据文件,
# 不显式收集会在打包产物里报 "unknown music source" / 找不到设备文件。
hiddenimports = collect_submodules('musicdl')
datas = collect_data_files('musicdl')
