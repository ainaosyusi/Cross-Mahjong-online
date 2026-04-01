# Oracle Cloud Always Free セットアップ手順

## 概要

| 項目 | 内容 |
|------|------|
| サービス | Oracle Cloud Infrastructure (OCI) Always Free |
| インスタンス | VM.Standard.E2.1.Micro (x86) |
| スペック | 1 OCPU / 1GB RAM（Always Free枠） |
| OS | Oracle Linux 9 |
| 用途 | Discord Bot 常時稼働 |
| 費用 | 無料 |

---

## Step 1: Oracle Cloud アカウント作成

1. https://www.oracle.com/cloud/free/ にアクセス
2. 「無料で始める」からアカウント登録
3. 必要情報を入力（クレジットカード登録が必要だが、Always Free枠では課金されない）
4. ホームリージョンを選択（**東京 (ap-tokyo-1)** 推奨）

> ⚠️ ホームリージョンは後から変更不可。東京を選ぶと日本からのレイテンシが最小

---

## Step 2: コンピュートインスタンス作成

1. OCI コンソール → **コンピュート** → **インスタンスの作成**

2. 設定値：

| 設定項目 | 値 |
|---------|-----|
| 名前 | `cross-mahjong-bot` |
| コンパートメント | デフォルト（root） |
| イメージ | **Canonical Ubuntu 22.04** (aarch64) |
| シェイプ | **VM.Standard.A1.Flex** (Ampere ARM) |
| OCPU数 | **1** |
| メモリ | **6 GB** |
| ブートボリューム | 47 GB（デフォルト） |

3. ネットワーク設定：
   - VCN: 新規作成（自動）
   - サブネット: パブリックサブネット
   - パブリック IPv4 アドレスの割当て: **はい**

4. SSHキーの追加：
   - 「SSHキーの追加」で公開鍵を登録、またはキーペアを生成してダウンロード

5. **「作成」** をクリック

> ⚠️ A1インスタンスは人気で在庫切れになることがある。取れない場合は時間を変えてリトライ

---

## Step 3: セキュリティルール設定

Bot はアウトバウンド通信（Discord API への接続）のみ使用するため、
インバウンドは SSH (22) のみ開放すれば十分。

### OCI セキュリティリスト（VCN設定内）

| 方向 | プロトコル | ポート | ソース | 用途 |
|------|----------|--------|--------|------|
| Ingress | TCP | 22 | 自分のIPまたは 0.0.0.0/0 | SSH接続 |
| Egress | All | All | 0.0.0.0/0 | Bot → Discord API 等 |

### OS ファイアウォール (iptables)

SSH接続後に実行：

```bash
# Ubuntu のデフォルト iptables ルールを確認・必要なら開放
sudo iptables -L
# 基本的にデフォルトのままで問題なし（アウトバウンドは許可済み）
```

---

## Step 4: サーバー環境構築

SSH でインスタンスに接続：

```bash
ssh -i <秘密鍵パス> ubuntu@<パブリックIP>
```

### 4.1 システム更新

```bash
sudo apt update && sudo apt upgrade -y
```

### 4.2 Python 環境

```bash
# Python 3.11+ をインストール
sudo apt install -y python3.11 python3.11-venv python3-pip

# Tesseract OCR（画像認識用）
sudo apt install -y tesseract-ocr tesseract-ocr-jpn

# OpenCV 依存ライブラリ
sudo apt install -y libgl1-mesa-glx libglib2.0-0
```

### 4.3 Bot用ディレクトリ作成

```bash
mkdir -p ~/cross-mahjong-bot
cd ~/cross-mahjong-bot

# 仮想環境作成
python3.11 -m venv venv
source venv/bin/activate

# 依存パッケージインストール（後でrequirements.txtを転送後に実行）
pip install -r requirements.txt
```

---

## Step 5: Bot デプロイ

### 5.1 ファイル転送

ローカルPCからインスタンスへ転送：

```bash
# ローカルPCで実行
scp -i <秘密鍵パス> -r ./cross-mahjong-bot/* ubuntu@<パブリックIP>:~/cross-mahjong-bot/
```

### 5.2 環境変数設定

```bash
cd ~/cross-mahjong-bot
cp .env.example .env
nano .env
```

`.env` に以下を設定：

```
DISCORD_TOKEN=your_bot_token_here
GUILD_ID=your_server_id_here
MATCHING_CHANNEL_ID=channel_id
RESULT_CHANNEL_ID=channel_id
RANKING_CHANNEL_ID=channel_id
```

---

## Step 6: systemd でBot を常時稼働

### 6.1 サービスファイル作成

```bash
sudo nano /etc/systemd/system/mahjong-bot.service
```

内容：

```ini
[Unit]
Description=Cross Mahjong Discord Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/cross-mahjong-bot
ExecStart=/home/ubuntu/cross-mahjong-bot/venv/bin/python bot.py
Restart=always
RestartSec=10
EnvironmentFile=/home/ubuntu/cross-mahjong-bot/.env

[Install]
WantedBy=multi-user.target
```

### 6.2 サービス登録・起動

```bash
sudo systemctl daemon-reload
sudo systemctl enable mahjong-bot    # 自動起動ON
sudo systemctl start mahjong-bot     # 起動
sudo systemctl status mahjong-bot    # 状態確認
```

### 6.3 ログ確認

```bash
# リアルタイムログ
sudo journalctl -u mahjong-bot -f

# 直近100行
sudo journalctl -u mahjong-bot -n 100
```

---

## Step 7: 自動バックアップ（SQLite）

cron で毎日 DB ファイルをバックアップ：

```bash
crontab -e
```

追加：

```
# 毎日 06:00 (JST) に SQLite バックアップ
0 21 * * * cp /home/ubuntu/cross-mahjong-bot/data/mahjong.db /home/ubuntu/cross-mahjong-bot/backups/mahjong_$(date +\%Y\%m\%d).db
```

```bash
mkdir -p ~/cross-mahjong-bot/backups
```

---

## 運用コマンドまとめ

| 操作 | コマンド |
|------|---------|
| Bot 起動 | `sudo systemctl start mahjong-bot` |
| Bot 停止 | `sudo systemctl stop mahjong-bot` |
| Bot 再起動 | `sudo systemctl restart mahjong-bot` |
| 状態確認 | `sudo systemctl status mahjong-bot` |
| ログ確認 | `sudo journalctl -u mahjong-bot -f` |
| コード更新後の再デプロイ | `scp` でファイル転送 → `sudo systemctl restart mahjong-bot` |

---

## 注意事項

- **Always Free枠の制限**: A1インスタンスは合計4 OCPU / 24GB RAMまで無料。1 OCPU / 6GBならBot用途に十分余裕あり
- **アイドル停止**: OCI は一定期間アイドル状態のインスタンスを停止する場合がある。Botが常時通信しているため通常は問題ないが、念のためモニタリング推奨
- **クレジットカード**: 登録必須だが、Always Free枠のみの利用であれば課金は発生しない
- **リージョン在庫**: 東京リージョンのA1は在庫切れになりやすい。取れない場合は大阪 (ap-osaka-1) も選択肢
