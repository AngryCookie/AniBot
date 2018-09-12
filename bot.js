const Discord = require('discord.js');
const client = new Discord.Client();
client.on('message', (message) => {
    let prefix = '.';
    if(message.content.indexOf(prefix) !== 0) return;
    const args = message.content.slice(prefix.length).trim().split(/ +/g);
    const command = args.shift().toLowerCase();
    if (command == 'mute' && message.member.hasPermission('MANAGE_ROLES')) {
        let member = message.mentions.members.first();
        if (!member) return;
        member.addRole('461227866869334019');
    }
});

client.login(process.env.TOKEN)