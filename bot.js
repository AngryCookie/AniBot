﻿const Discord = require('discord.js');
const client = new Discord.Client();
client.on('message', (message) => {
    let prefix = '.';
    if(message.content.indexOf(prefix) !== 0) return;
    const args = message.content.slice(prefix.length).trim().split(/ +/g);
    const command = args.shift().toLowerCase();
    if (command == 'mute') {
        let member = message.mentions.members.first();
        if (!member) return;
        member.addRole('id роли мута');
    }
});

client.login(process.env.TOKEN)