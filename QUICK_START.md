# 🚀 GUIDE DE DÉMARRAGE RAPIDE

## Pour une NOUVELLE installation

```bash
# 1. Installer les dépendances
pip install python-telegram-bot aiosqlite python-dotenv

# 2. Configurer le .env
echo "BOT_TOKEN=your_bot_token_here" > .env
echo "ADMIN_IDS=your_user_id" >> .env

# 3. Lancer le bot
python bot.py
```

**C'est tout! ✅** Toutes les nouvelles fonctionnalités sont déjà incluses.

---

## Pour METTRE À JOUR une installation existante

```bash
# 1. IMPORTANT : Backup de la base de données
cp autocaption.db autocaption.db.backup

# 2. Migrer la base de données
python migrate_db.py

# 3. (Optionnel) Tester les nouvelles fonctionnalités
python test_features.py

# 4. Redémarrer le bot
python bot.py
```

---

## ⚡ TESTER LES NOUVELLES FONCTIONNALITÉS

### 1️⃣ Statistiques détaillées

En tant qu'admin, envoyez :
```
/status
```

Vous verrez maintenant :
```
👥 Users:
• Total: 2
• Active (1 hour): 2
• Active (24 hours): 2
• Active (7 days): 2
• Inactive (7+ days): 0
```

---

### 2️⃣ Broadcast (Message à tous les utilisateurs)

**Option A : Message texte**
```
/broadcast Bonjour à tous ! 🎉
```

**Option B : Transférer un message (avec photo/vidéo)**
1. Envoyez une photo/vidéo
2. Répondez à ce message avec `/broadcast`
3. Le message sera copié à tous les utilisateurs

**Résultat :**
```
✅ Broadcast Complete

👥 Total: 150
✅ Success: 142
🚫 Blocked: 6
❌ Failed: 2
```

---

### 3️⃣ Cache Force-Join (Automatique)

Le cache est déjà actif ! Il fonctionne automatiquement en arrière-plan :
- Réduit les appels API à Telegram
- Cache de 5 minutes
- Améliore la vitesse de réponse du bot

**Aucune configuration nécessaire** ✅

---

## 📋 COMMANDES ADMIN DISPONIBLES

| Commande | Description |
|----------|-------------|
| `/status` | Statistiques détaillées (avec activité utilisateurs) |
| `/broadcast <msg>` | Envoyer un message à tous les utilisateurs |
| `/forceon` | Activer le force-join |
| `/forceoff` | Désactiver le force-join |
| `/addforce @channel` | Ajouter une chaîne obligatoire |
| `/delforce -100123456` | Supprimer une chaîne |
| `/forcelist` | Lister les chaînes obligatoires |

---

## 🔧 CONFIGURATION (Variables d'environnement)

Créez un fichier `.env` :

```env
# OBLIGATOIRE
BOT_TOKEN=123456:ABCdefGHIjklMNOpqrsTUVwxyz

# OBLIGATOIRE - Votre User ID Telegram
ADMIN_IDS=123456789

# OPTIONNEL
SQLITE_PATH=autocaption.db
HELP_URL=https://telegra.ph/your-guide

# DEBUG (décommenter pour activer)
# DEBUG=1
# ECHO_ALL=1
```

**Comment obtenir votre User ID ?**
1. Envoyez un message à [@userinfobot](https://t.me/userinfobot)
2. Il vous donnera votre ID
3. Ajoutez-le dans `.env` : `ADMIN_IDS=votre_id`

**Pour plusieurs admins :**
```env
ADMIN_IDS=123456789,987654321,555555555
```

---

## ✅ VÉRIFICATION RAPIDE

Après le démarrage du bot, vérifiez :

```bash
# 1. Le bot devrait afficher :
Auto-Caption Bot started as @YourBotUsername (id=...)

# 2. Testez avec /start
# Vous devriez voir toutes les commandes, y compris /broadcast

# 3. En tant qu'admin, testez /status
# Vous devriez voir les statistiques détaillées

# 4. Testez un broadcast
/broadcast Test message
```

Si tout fonctionne, vous êtes prêt ! 🎉

---

## 🆘 PROBLÈMES COURANTS

### ❌ "Module not found: telegram"
```bash
pip install python-telegram-bot
```

### ❌ "Module not found: aiosqlite"
```bash
pip install aiosqlite
```

### ❌ "Column last_activity doesn't exist"
```bash
python migrate_db.py
```

### ❌ "/broadcast ne fonctionne pas"
- Vérifiez que votre User ID est dans `ADMIN_IDS`
- La commande est réservée aux admins uniquement

### ❌ "Stats affichent 0 utilisateurs actifs"
- Normal après une migration
- Les stats se rempliront progressivement quand les utilisateurs interagissent

---

## 📊 COMPARAISON AVANT/APRÈS

### AVANT (Version 1.0)
```
/status affichait :
👤 Your status
• Captions: 3
• Active: One Piece — Full HD — VF (next: 12)

🛡 Global
• Users: 150
• Files: 1234
• Storage: 5.67 GB
```

### APRÈS (Version 2.0) ⭐
```
/status affiche maintenant :
👤 Your status
• Captions: 3
• Active: One Piece — Full HD — VF (next: 12)

👥 Users:
• Total: 150
• Active (1 hour): 12
• Active (24 hours): 45
• Active (7 days): 89
• Inactive (7+ days): 61

🛡 System
• Files: 1234
• Storage: 5.67 GB
• Force: ON (2)
• Uptime: 12h 34m 56s
```

**+ Nouvelle commande `/broadcast`** 📢

---

## 🎯 PROCHAINES ÉTAPES

1. ✅ Testez les nouvelles fonctionnalités
2. 📊 Suivez vos statistiques quotidiennes
3. 📢 Utilisez broadcast pour vos annonces
4. 🚀 Profitez de la meilleure performance (cache)

---

**Besoin d'aide ?**
- Consultez [CHANGELOG.md](CHANGELOG.md) pour la documentation complète
- Consultez [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) pour les détails techniques

**Bon déploiement ! 🚀**
