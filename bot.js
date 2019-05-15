const Discord = require(`discord.js`);
const request = require("request");
const ms = require("ms");
const client = new Discord.Client({disableEveryone : true});

let p = "s!"
let c = '#363940'

////////////////////////////////
client.login(process.env.TOKEN); //
////////////////////////////////
client.on('ready', () => {   ///
    client.user.setActivity("за твоей мамой", {type: "WATCHING"});
console.log("Запущен!");    ////
});                         ////
////////////////////////////////
////////////////////////////////
client.on('message', message => {
    const args = message.content.slice(p.length).trim().split(/ +/g);
    const command = args.shift().toLowerCase();
if(message.content.startsWith(p + 'say')) {
    let say = message.content.slice((p + 'say').length);
    message.channel.send(say);
   }
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
   if(message.content.startsWith(p + 'help')) {
    const embed = new Discord.RichEmbed()
        .setColor(c)
        .setTitle("Помощь от Кота")
        .setDescription("Данный бот был создан для сервера FlexHub")
        .addField("OTHER","`s!say` - сказать что-то от именни бота\n`s!ping` - проверить нагрузку на бота\n`s!report`  - написать репорт на человека")
        .addField("MODER","`s!kick` - кикнуть пользователя\n`s!ban` - забанить пользователя\n`s!report` - написать жалобу\n`s!server` - проверить информацию про данный сервер")
        .addField("FUN","s!hi - сказать привет!\ns!sad - уйти в печаль\ns!angry - начать злится\ns!sleep - пойти спать\ns!suicide - сделать смэрть\ns!smoke - выкурить сигу")
        try {
            message.author.send(embed).then(m =>{
            message.channel.send("**Проверь личные сообщение**");	
            })
        } catch (err) {
            message.channel.send("Ваши личные сообщения заблокированы.");
        }        
}
////////////////////////////////////////////////////////////
////////////////////////////////////////////////////////////
if(message.content.startsWith(p + 'kick')) {
    if(bUser.hasPermission("KICK_MEMBERS")) return message.channel.send("У тебя нет прав!");
    return message.reply("У тебя нет прав!");
    const Kmember = message.mentions.members.first();
    const reason = args.slice(1).join(' ');
    if (!reason) reason = "Без причины";
    if (Kmember.kickable) { 
        Kmember.kick(`${reason}`);
        message.channel.send(`${Kmember} был кикнут по причине **${reason}**`);
    } else (`Не удалось ${Kmember} кикнуть`);
    const kickEmbed = new Discord.RichEmbed()
    .setDescription("КИК от Котейки")
    .setColor(c)
    .addField("Кикнут", `${Kmember} ID ${Kmember.id}`)
    .addField("Кикнул", `<@${message.author.id}> ID ${message.author.id}`)
    .addField("Кикнут в", message.channel)
    .addField("Время", message.createdAt)
    .addField("Причина", reason);
    let incidentchannel = message.guild.channels.find(`name`, "логи");
    if(!incidentchannel) return message.channel.send("Я не могу найти канал `логи`");
    incidentchannel.send(kickEmbed);
    return;
}
if(message.content.startsWith(p + 'ban')) {
    let bUser = message.guild.member(message.mentions.users.first() || message.guild.members.get(args[0]));
    if(!bUser) return message.channel.send("Нет такого");
    let bReason = args.join(" ").slice(22);
    if(!message.member.hasPermission("MANAGE_MEMBERS")) return message.channel.send("No can do pal!");
    if(bUser.hasPermission("BAN_MEMBERS")) return message.channel.send("У тебя нет прав!");
    const banEmbed = new Discord.RichEmbed()
    .setDescription("БАН от Котейки")
    .setColor(c)
    .addField("Забанили", `${bUser} ID ${bUser.id}`)
    .addField("Забанил", `<@${message.author.id}> ID ${message.author.id}`)
    .addField("Забанен в", message.channel)
    .addField("Время", message.createdAt)
    .addField("Причина", bReason);
    let incidentchannel = message.guild.channels.find(`name`, "логи");
    if(!incidentchannel) return message.channel.send("Я не могу найти канал `логи`");
    incidentchannel.send(banEmbed);
    message.guild.member(bUser).ban(bReason);
    return;
  }
  if(message.content.startsWith(p + 'report')) {
    let rUser = message.guild.member(message.mentions.users.first() || message.guild.members.get(args[0]));
    if(!rUser) return message.channel.send("не могу найти его");
    let rreason = args.join(" ").slice(22);
    let reportEmbed = new Discord.RichEmbed()
    .setDescription("Котейка репорт показал")
    .setColor(c)
    .addField("Пользователь", `${rUser} ID ${rUser.id}`)
    .addField("Репорт сделал", `${message.author} ID ${message.author.id}`)
    .addField("Каанал", message.channel)
    .addField("Время", message.createdAt)
    .addField("Причина", rreason);
    let reportschannel = message.guild.channels.find(`name`, "💡┇репорт");
    if(!reportschannel) return message.channel.send("Я не нашёл канал `💡┇репорт`");
    message.delete().catch(O_o=>{});
    reportschannel.send(reportEmbed);
    return;
  }
  if(message.content.startsWith(p + 'server')) {
    let sicon = message.guild.iconURL;
    const serverembed = new Discord.RichEmbed()
    .setDescription("Информация про сервер")
    .setColor(c)
    .setThumbnail(sicon)
    .addField("Название", message.guild.name)
    .addField("Создан", message.guild.createdAt)
    .addField("Ты сюда попал", message.member.joinedAt)
    .addField("Сколько человек", message.guild.memberCount);
    return message.channel.send(serverembed);
  }
  if(message.content.startsWith(p + 'mute')) {
  let tomute = message.guild.member(message.mentions.users.first() || message.guild.members.get(args[0]));
  if(!tomute) return message.reply("я его не нашёл");
  if(tomute.hasPermission("KICK_MEMBERS")) return message.reply("ты не можешь это сделать");
  let muterole = message.guild.roles.find(`name`, "muted");
  if(!muterole){
    try{
      muterole = message.guild.createRole({
        name: "muted",
        color: "#000000",
        permissions:[]
      })
      message.guild.channels.forEach(async (channel, id) => {
          channel.overwritePermissions(muterole, {
          SEND_MESSAGES: false,
          ADD_REACTIONS: false
        });
      });
    }catch(e){
      console.log(e.stack);
    }
  }
  let mutetime = args[1];
  if(!mutetime) return ("ВРЕМЯ УКАЖИ!");
 (tomute.addRole(muterole.id));
  (`<@${tomute.id}> был замучен на **${ms(ms(mutetime))}**`);
  setTimeout(function(){
    tomute.removeRole(muterole.id);
    message.channel.send(`<@${tomute.id}> был размучен!`);
  }, ms(mutetime));
}
if (message.content.startsWith(p + 'ping')) {
    const embed = new Discord.RichEmbed()
.setColor(c)
.setDescription('\n **Pong!** `' + `${Date.now() - message.createdTimestamp}` + ' ms` \n') 
message.channel.send({embed});
}
/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////
if (message.content.startsWith(p + `hi`)) {
    message.delete();
    message.delete();
const urls = [
    "https://media.tenor.com/images/824a5c6fb0eff4de202d0cd4da1e6692/tenor.gif",//1
"https://steamusercontent-a.akamaihd.net/ugc/1617175662597177927/732757601CDBF2E52C41EF3349035A337BB119D7/",//2
"https://image.noelshack.com/fichiers/2018/17/3/1524685070-df0a9rx.gif",//3
"https://thumbs.gfycat.com/HatefulBlindFunnelweaverspider-size_restricted.gif",//4
"https://thumbs.gfycat.com/AdorableFormalAngwantibo-size_restricted.gif",//5
"https://pa1.narvii.com/6505/ad5549ff5f252cd35e393f88c55d474ab83fd46d_hq.gif",//6
"http://gifimage.net/wp-content/uploads/2017/10/hi-anime-gif-9.gif",//7
"https://kingmarsblog.files.wordpress.com/2016/08/c5612569563abae86b811071616e4c07f5b3aa18_hq.gif?w=882",//8
"https://media.tenor.com/images/b96f06f81933f49b6d24577017eb4edd/tenor.gif",//9
"https://media.giphy.com/media/yyVph7ANKftIs/giphy.gif",//10
"https://media1.tenor.com/images/c2e21a9d8e17c1d335166dbcbe0bd1bf/tenor.gif?itemid=5459102",//11
"http://gifimage.net/wp-content/uploads/2017/10/hi-anime-gif-11.gif",//12
"https://data.whicdn.com/images/233897767/original.gif",//13
"http://i.imgbox.com/AYqk4UJk.gif",//14
"https://cdn105.picsart.com/203730462001202.gif?r1024x1024",//15
"https://thumbs.gfycat.com/HauntingNeighboringBarracuda-max-1mb.gif",//16
"http://pa1.narvii.com/5935/a557baffc06658c5b3c2932eb0bc496cb112d04c_00.gif",//17
"https://thumbs.gfycat.com/ArtisticVelvetyBarebirdbat-max-1mb.gif",
"https://media1.tenor.com/images/ae40603eddb6e4bb1ea56cc6de7d0f6e/tenor.gif?itemid=5142315",
"https://media.tenor.com/images/21f53e7521c2262f778cb71bd671522b/tenor.gif",
"https://media.tenor.com/images/73ce6a152fdf3fa2645f6153c646c9b7/tenor.gif",
"https://image.myanimelist.net/ui/z9mCAeIYypLkQQhpPKgdnaknwcoChRZHEz5uuGvWqjGX9hQXPKVaIgGJhk17VmmwNuay0ifX7duQKIoAzhryEWr3Rof3GZ_OaH5gLoVMkOU",
"https://pa1.narvii.com/6749/99edaa75487131db6d433c0c9442051f6314452c_hq.gif",
"http://gifimage.net/wp-content/uploads/2017/10/hello-anime-gif-7.gif",
"https://i.kym-cdn.com/photos/images/newsfeed/001/402/477/2ec.gif",
"https://media1.tenor.com/images/943a3f95936d66dc0c78fd445893431e/tenor.gif?itemid=9060940",
"https://image.myanimelist.net/ui/_D9BvY42y5B3XjqszccZEcQ2SNP8h5106Ssqd0yjIoOLHYVPNM4QRf3QlKgAuc3crFW1imwGXqnkBUWKef6Xz6ux7UeaqIiqrDQNmkpinsaSrt7QBBqeEk5M-IkPP4mA",
"https://pa1.narvii.com/6482/b4862bba0a3633b3bb3e6f4b6a72b8047f932c4a_hq.gif"
];
    let user = message.author;
    let user1 = message.mentions.users.first();
    const selfbite = new Discord.RichEmbed()
                    .setDescription(message.author+` сказал(а) всем привет`)
                    .setImage((urls[Math.floor(Math.random() * urls.length)]))
                    .setColor(c); 
    if (!user1 || user1.id === user.id) return message.channel.send(selfbite).then(function(message) {
                    }).catch(function() {});
                let embed = new Discord.RichEmbed()
                    .setDescription(message.author+` сказал(а) привет `+message.mentions.users.first())
                    .setImage((urls[Math.floor(Math.random() * urls.length)]))
                    .setColor(c)
                    message.channel.send(embed
                    ).then(function(message) {
                    }).catch(function() {});
}
if (message.content.startsWith(p + `sad`)) {
    message.delete();
    let user = message.author;
    message.channel.send('Загрузка...').then(msg => {
        const urls = [
"https://avatars.mds.yandex.net/get-pdb/805781/67906d0f-bda7-47a3-92d2-4ce1b4f728fd/orig",
"https://pa1.narvii.com/5821/76ddb33055d9574ccd11e051df968b4fbe5dcd18_hq.gif",
"https://i.pinimg.com/originals/94/2f/84/942f84de5d7471ab9751f2ba86e63b60.gif",
"https://steamusercontent-a.akamaihd.net/ugc/919176676388266575/8BA8145FF1760B8E60083656286E266B0DED1AA2/",
"https://pa1.narvii.com/5696/d3b317bb82fc086da90220a72cf6bfdc779e60e7_hq.gif",
"https://media.giphy.com/media/Gy7OHqaWnJBO8/giphy.gif",
"https://steamusercontent-a.akamaihd.net/ugc/2425628008261954271/007DB92C3AF029AFBBB07DFEEB1712F8B84DDDC7/?interpolation=lanczos-none&output-format=jpeg&output-quality=95&fit=inside%7C500%3A250&composite-to=*,*%7C500%3A250&background-color=black",
"http://33.media.tumblr.com/8c701e63bdc00912c845953d57ea6097/tumblr_n3enupTctr1s2fmtuo1_500.gif",
"http://68.media.tumblr.com/4851cb0953a11f1e7a1da93c81a5bd97/tumblr_nz64zkMqPi1qe1bdeo1_500.gif",
"http://68.media.tumblr.com/2c6646ae33f53db3c4b46e2784debe61/tumblr_og7o1nlSWo1vctqxpo1_500.gif",
"http://68.media.tumblr.com/2190867b663ede80c0eea49fa5f9ac2b/tumblr_og7o2dhSc71vctqxpo1_500.gif",
"https://steamusercontent-a.akamaihd.net/ugc/923672032480155593/F58137E290C57DAA9FB7B3ED1EAC69777C76DCCF/",
"http://gifimage.net/wp-content/uploads/2017/07/anime-sad-gif-9.gif",
"http://gifimage.net/wp-content/uploads/2017/07/anime-sad-gif-15.gif",
"https://media.giphy.com/media/FB5EOw0CaaQM0/giphy.gif",
"https://thumbs.gfycat.com/CommonDownrightAndeancondor-small.gif",
"https://i.pinimg.com/originals/19/42/07/194207dd9df329dcc66bf0bc07eefe8c.gif"
];
let embed = new Discord.RichEmbed()
      .setDescription(`${user} Ушел(ла) в печаль`)
      .setImage(urls[Math.floor(Math.random() * urls.length)])
      .setColor(c)
  msg.edit({embed}).then(function(message) {
      }).catch(function() {});
});
}
if (message.content.startsWith(p + `smoke`)) {
    message.delete();
    let user = message.author;
                  message.channel.send('Загрузка...').then(msg => {
         const urls = ['https://thumbs.gfycat.com/SphericalDependentHalibut-small.gif', 'https://78.media.tumblr.com/7746fca41c6782df47d7cd6925adba6f/tumblr_orcpabAWTV1sqhf08o1_500.gif', 'http://animeonline.su/uploads/posts/2015-06/1435137244_end.gif', 'https://media.giphy.com/media/hnRXZQiHWTtTO/giphy.gif', 'https://media.giphy.com/media/1k6S4iyfFyTRK/giphy.gif' ,'https://i.pinimg.com/originals/10/4b/9e/104b9ea0f2dea93d9374b092b82e1256.gif', 'https://s3-eu-west-1.amazonaws.com/files.surfory.com/uploads/2015/2/14/54dd05a41f395d0b468b465a/54df5bf31f395daa438b4c8e.gif', 'http://s8.favim.com/orig/150926/anime-guy-black-and-white-gif-smoking-Favim.com-3361618.gif', 'http://img0.safereactor.cc/pics/post/anime-gif-Anime-Subete-ga-F-ni-Naru-The-Perfect-Insider-2638766.gif', 'http://s017.radikal.ru/i424/1111/2b/ecae2f095abb.gif', 'https://78.media.tumblr.com/5bec6027d1c27194e6d3d5863c739d5f/tumblr_ozmfkvy8Pc1urnatuo1_500.gif', 'https://78.media.tumblr.com/6ac2528e3cde0894adb41fbc4e56def0/tumblr_owayv78WNu1vbfbhho1_500.gif'];
         let embed = new Discord.RichEmbed()
                    .setDescription(`${user} выкурил(а) сигарету`)
                    .setImage(urls[Math.floor(Math.random() * urls.length)])
                    .setColor(c)
                msg.edit({embed}).then(function(message) {
                    }).catch(function() {});
    });
}
if (message.content.startsWith(p + `sleep`)) {
    message.delete();
    let user = message.author;
                  message.channel.send('Загрузка...').then(msg => {
                      const urls = ['https://media1.tenor.com/images/0d78943ec2d800847bfe98c0a5e03cd3/tenor.gif?itemid=11081269','https://thumbs.gfycat.com/DrearyDenseFlicker-size_restricted.gif','https://i.pinimg.com/originals/24/3e/2f/243e2f0cf4ad9ef9fb9def7594ec2c85.gif','https://thumbs.gfycat.com/SadWiltedHackee-small.gif','https://media.tenor.com/images/9bbd2789c5eaf20198205ca4976dda75/tenor.gif','https://data.whicdn.com/images/233322524/original.gif','https://gifer.com/i/8hQS.gif','http://gifimage.net/wp-content/uploads/2018/05/sleep-anime-gif-4.gif','https://media1.tenor.com/images/6f04cbe23fa862cd1e7da987c2b0308e/tenor.gif?itemid=9187874','https://i.pinimg.com/originals/92/8c/d7/928cd76c937e2f4c6d998651c2c88d58.gif','https://vignette.wikia.nocookie.net/kancolle/images/0/08/Umaru_sleeping.gif/revision/latest?cb=20161209020902','https://gifer.com/i/WDf.gif','https://i.imgur.com/Sb8Wls5.gif','https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcSu7Otqu-VpJAr92BOMTtSJkJLxMWBD_l6Yd41tCkxKzDxUWOCB9g','https://i.kym-cdn.com/photos/images/original/001/115/759/095.gif'];//12321312312
                      let embed = new Discord.RichEmbed()
                    .setDescription(`${user} пошел(шла) спать.`)
                    .setImage(urls[Math.floor(Math.random() * urls.length)])
                    .setColor(c)
                msg.edit({embed}).then(function(message) {
    
                }).catch(function() {});
    });
}
if (message.content.startsWith(p + `suicide`)) {
    message.delete();
    let user = message.author;
    message.channel.send('Загрузка...').then(msg => {
     const urls = ['https://lh3.googleusercontent.com/-buUYgrq_wKc/VRO0gc7EHqI/AAAAAAAAAG0/7Ntm-6fFkk4/w500-h288/naomi%2Bsuicide%2Bgif.gif', 'https://uploads.disquscdn.com/images/2dbbc921cb13de3198a3b6ae0099e725bfb0c80129d70bacf47819fb765deef1.gif', 'http://37.media.tumblr.com/tumblr_m7ram5jIAA1qzbqw1o1_250.gif', 'https://i.pinimg.com/originals/79/2f/37/792f37131d123c568e7114b7b829e572.gif', 'http://thisisinfamous.com/wp-content/uploads/2014/12/tumblr_ngjphxwU011t3zq0no1_400.gif', 'httpsimage.net/wp-content/uploads/2017/07/anime-suicide-gif-15.gif', 'https://data.whicdn.com/images/290510883/original.gif', 'https://media.giphy.com/media/WsWJZcJoxmLUk/giphy.gif', 'https://media1.tenor.com/images/a5db1c26b710b8b834d8265bf97a6c79/tenor.gif?itemid=5091706', 'http://38.media.tumblr.com/c75ba943c38bad612d9e722ee3142bb3/tumblr_n418yewq601tubxydo1_500.gif', 'http://66.media.tumblr.com/e2ab4fd11151e5e8acc627254bb7594d/tumblr_mo1ef0QwUS1s0pcfao1_500.gif', 'https://i.gifer.com/3ZvS.gif', 'http://gifimage.net/wp-content/uploads/2017/07/anime-suicide-gif-8.gif', 'https://i.pinimg.com/originals/a5/f1/96/a5f196464ed42f493b95a600099e83b9.gif', 'https://cdn60.picsart.com/182542841000202.gif?r1024x1024', 'https://zippy.gfycat.com/EquatorialGleefulArabianhorse.gif', 'http://data.whicdn.com/images/107593752/large.gif', 'https://i.gifer.com/Rk5D.gif', 'https://pa1.narvii.com/6535/3eb238ede3ccbc364d487c60f9d8b9c9fcb4f515_hq.gif', 'http://gifimage.net/wp-content/uploads/2017/07/anime-suicide-gif-2.gif'];
                let embed = new Discord.RichEmbed()
                    .setDescription(`${user} совершил(а) суицид`)
                    .setImage(urls[Math.floor(Math.random() * urls.length)])
                    .setColor(c)
                    msg.edit({embed}).then(function(message) {
                    }).catch(function() {});
              });
              }
              if (message.content.startsWith(p + `angry`)) {
                message.delete();
                 let user = message.author;
                let user1 = message.mentions.users.first();
                const urls = ['https://data.whicdn.com/images/33545835/original.gif', 'http://i.imgur.com/P8oGR3u.gif', 'https://data.whicdn.com/images/283566570/original.gif', 'https://i.pinimg.com/originals/ac/e0/61/ace061704cb13602222916265471073e.gif', 'http://media.giphy.com/media/hFVI29iuk2wFy/giphy.gif', 'https://media.giphy.com/media/o7C2BKtp6gSd2/giphy.gif', 'https://i.pinimg.com/originals/83/32/8b/83328b8fd0238f801e61ca07faa6a000.gif', 'https://data.whicdn.com/images/104935742/original.gif', 'http://roxannemodafferi.net/RBlog/wp-content/uploads/2018/05/angry-anime-girl-gif.gif', 'https://i.pinimg.com/originals/13/e2/76/13e2761232d7671a9c2663aca5b9dbf2.gif']
                const selfbite = new Discord.RichEmbed()
                                .setDescription(`${user} злится`)
                                .setImage((urls[Math.floor(Math.random() * urls.length)]))
                                .setColor(c)
                if (!user1 || user1.id === user.id) return message.channel.send(selfbite).then(function(message) {
                                }).catch(function() {});
                            let embed = new Discord.RichEmbed()
                                .setDescription(`${user} злится на ${user1}`)
                                .setImage((urls[Math.floor(Math.random() * urls.length)]))
                                .setColor(c) 
                                message.channel.send(embed
                                ).then(function(message) {
                                }).catch(function() {});
            }
            if (message.content.startsWith(p + `bang`)) {
                message.delete();
                if (!user1 || user1.id === user.id) return message.channel.send(selfbite).then(function(message) {
                }).catch(function() {});
                 let user = message.author;
                let user1 = message.mentions.users.first();
                const urls = ['https://tenor.com/view/jormungand-anime-shoot-gif-13757300', 'https://tenor.com/view/anime-shooting-gif-8118409', 'https://tenor.com/view/nichijou-gatlinggun-anime-shoot-gif-5359419', 'https://tenor.com/view/gun-fire-anime-shoot-blam-gif-5256396', 'https://tenor.com/view/anime-agent-aika-shooting-gun-gif-13871978', 'https://tenor.com/view/llenn-running-power-anime-gun-gif-12047152', 'https://tenor.com/view/chibiusa-anime-sailor-moon-small-lady-gun-gif-13671547', 'https://tenor.com/view/anime-wolfwood-aim-shoot-gun-gif-12206815', 'https://tenor.com/view/reisen-anime-power-shoot-gif-7245361', 'https://tenor.com/view/anime-no-mirai-nikki-shoot-calm-gif-12525522', 'https://tenor.com/view/anime-finger-gun-ishoot-you-gif-13451225', 'https://tenor.com/view/anime-agent-aika-shooting-gun-gif-13871976', 'https://tenor.com/view/osomatsusan-ichimatsu-karamatsu-anime-bazooka-shoot-gif-5706794','https://tenor.com/view/doraemon-shoots-gun-anime-gif-7174362']
                            let embed = new Discord.RichEmbed()
                                .setDescription(`${user} застрелил(а) ${user1}`)
                                .setImage((urls[Math.floor(Math.random() * urls.length)]))
                                .setColor(c) 
                                message.channel.send(embed
                                ).then(function(message) {
                                }).catch(function() {});
                            }
/////////////////////////////////////////////////////////////
/////////////////////////////////////////////////////////////
});
