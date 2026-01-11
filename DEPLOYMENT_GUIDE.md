# 🚀 GUIDE DE DÉPLOIEMENT - SERVEUR CONTABO

## 📍 Tu es connecté à : `root@vmi2736931`

---

## 🛑 ÉTAPE 1 : ARRÊTER LE BOT ACTUEL

Copie-colle ces commandes **une par une** sur ton serveur :

### 1️⃣ Vérifier les processus Python en cours
```bash
ps aux | grep python
```

Tu verras quelque chose comme :
```
root     12345  0.5  2.3  bot.py
root     12346  0.0  0.1  grep python
```

### 2️⃣ Arrêter tous les bots Python
```bash
pkill -f bot.py
```

### 3️⃣ Vérifier que le bot est bien arrêté
```bash
ps aux | grep python
```

Si tu vois encore un processus, tue-le avec son PID :
```bash
kill -9 12345
```

---

## 📥 ÉTAPE 2 : METTRE À JOUR LE CODE

### 1️⃣ Aller dans le dossier du bot
```bash
cd ~/CAPTIONBOT
# OU si c'est ailleurs :
# cd /root/bot
# cd /opt/bot
# find / -name "bot.py" 2>/dev/null
```

### 2️⃣ Faire un backup de la base de données
```bash
cp autocaption.db autocaption.db.backup-$(date +%Y%m%d-%H%M%S)
ls -lh autocaption.db*
```

### 3️⃣ Uploader les nouveaux fichiers

**Option A : Via Git (si tu utilises Git)**
```bash
git pull origin main
```

**Option B : Via SCP depuis ton PC**
Ouvre un **nouveau terminal PowerShell sur Windows** :
```powershell
scp -r "C:\Users\djohn\Downloads\UPLOADERBOT\BOBOTBOY\CAPTIONBOT\*" root@vmi2736931.contaboserver.net:~/CAPTIONBOT/
```

**Option C : Via SFTP/FileZilla**
1. Connecte-toi avec FileZilla
2. Upload tous les fichiers Python modifiés :
   - `bot.py`
   - `config.py`
   - `admin.py`
   - `migrate_db.py`

---

## 🔄 ÉTAPE 3 : MIGRATION DE LA BASE DE DONNÉES

Sur le serveur :
```bash
cd ~/CAPTIONBOT
python3 migrate_db.py
```

Tu devrais voir :
```
[OK] Migration completed successfully!
   - Added last_activity column
   - Updated X existing users
```

---

## ⚙️ ÉTAPE 4 : VÉRIFIER LES VARIABLES D'ENVIRONNEMENT

```bash
cat .env
```

Assure-toi que le fichier contient :
```
BOT_TOKEN=8487001863:AAH9Ah05GpIwP6zT3dJGeP6oxc3CFYFsxtE
ADMIN_IDS=7570539064,7615697178
HELP_URL=https://telegra.ph/Auto-Caption-Bot-09-24
```

Si le fichier n'existe pas ou est incorrect, crée-le :
```bash
cat > .env << 'EOF'
BOT_TOKEN=8487001863:AAH9Ah05GpIwP6zT3dJGeP6oxc3CFYFsxtE
ADMIN_IDS=7570539064,7615697178
HELP_URL=https://telegra.ph/Auto-Caption-Bot-09-24
EOF
```

---

## 🚀 ÉTAPE 5 : REDÉMARRER LE BOT

### Option A : Avec screen (recommandé)
```bash
# Créer une nouvelle session screen
screen -S captionbot

# Lancer le bot
python3 bot.py

# Détacher la session : Ctrl+A puis D
# Pour se reconnecter plus tard :
# screen -r captionbot
```

### Option B : Avec nohup
```bash
nohup python3 bot.py > bot.log 2>&1 &
```

### Option C : Avec systemd (service permanent)
```bash
# Créer le service
cat > /etc/systemd/system/captionbot.service << 'EOF'
[Unit]
Description=Auto Caption Bot
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/CAPTIONBOT
ExecStart=/usr/bin/python3 /root/CAPTIONBOT/bot.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Activer et démarrer le service
systemctl daemon-reload
systemctl enable captionbot
systemctl start captionbot

# Vérifier le statut
systemctl status captionbot

# Voir les logs
journalctl -u captionbot -f
```

---

## ✅ ÉTAPE 6 : VÉRIFIER QUE LE BOT FONCTIONNE

### Sur le serveur :
```bash
# Voir les logs en temps réel
tail -f bot.log

# OU si tu utilises systemd :
journalctl -u captionbot -f
```

Tu devrais voir :
```
Auto-Caption Bot started as @auttocaptionbot (id=8487001863)
```

### Sur Telegram :
1. Envoie `/start` au bot
2. Envoie `/status` (en tant qu'admin)
3. Vérifie les nouvelles statistiques

---

## 🔧 COMMANDES UTILES

### Arrêter le bot
```bash
# Si lancé avec screen
screen -r captionbot
# Puis Ctrl+C

# Si lancé avec systemd
systemctl stop captionbot

# Si lancé avec nohup
pkill -f bot.py
```

### Redémarrer le bot
```bash
systemctl restart captionbot
```

### Voir les logs
```bash
# Avec systemd
journalctl -u captionbot -f

# Avec nohup
tail -f bot.log
```

### Trouver le bot en cours
```bash
ps aux | grep bot.py
```

---

## 🆘 DÉPANNAGE

### Le bot ne démarre pas
```bash
# Vérifier les dépendances
pip3 install -r requirements.txt

# OU installer manuellement
pip3 install python-telegram-bot aiosqlite python-dotenv
```

### Erreur "column not found"
```bash
# Re-exécuter la migration
python3 migrate_db.py
```

### Le bot se ferme tout seul
```bash
# Vérifier les logs pour voir l'erreur
cat bot.log
# OU
journalctl -u captionbot -n 50
```

---

## 📊 VÉRIFICATION POST-DÉPLOIEMENT

### ✅ Checklist :
- [ ] Bot arrêté sur le serveur
- [ ] Backup de `autocaption.db` créé
- [ ] Nouveaux fichiers uploadés
- [ ] Migration exécutée : `python3 migrate_db.py`
- [ ] Variables `.env` correctes
- [ ] Bot redémarré
- [ ] `/start` fonctionne
- [ ] `/status` affiche les nouvelles stats
- [ ] `/broadcast` disponible

---

## 🎯 RÉSUMÉ EN 5 COMMANDES

Si tu veux faire vite, voici les commandes essentielles :

```bash
# 1. Arrêter le bot
pkill -f bot.py

# 2. Aller dans le dossier
cd ~/CAPTIONBOT

# 3. Backup DB
cp autocaption.db autocaption.db.backup

# 4. Migration (après upload des nouveaux fichiers)
python3 migrate_db.py

# 5. Redémarrer
screen -S captionbot
python3 bot.py
# Ctrl+A puis D pour détacher
```

---

**Bon déploiement ! 🚀**

Si tu as des erreurs, partage-les et je t'aiderai à les résoudre !
