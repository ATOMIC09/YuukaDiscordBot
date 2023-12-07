import discord
from discord.ext import commands
from discord import app_commands
import requests
import json
from bs4 import BeautifulSoup

class SearchByImage(commands.Cog):
    def __init__(self, client: commands.Bot):
        self.client = client
        self.log_cog = client.get_cog("Log")
        self.context_menu = app_commands.ContextMenu(
            name='Search by Image',
            callback=self.searchbyimage,
        )
        self.client.tree.add_command(self.context_menu)

    @commands.Cog.listener()
    async def on_ready(self):
        print("SearchByImage cog loaded")

    async def searchbyimage(self, interaction: discord.Interaction, message: discord.Message):
        try:
            await self.log_cog.sendlog(interaction, data={'content': message.attachments[0].filename})
        except IndexError:
            await interaction.response.send_message(f"❌ **[ไม่พบภาพที่ถูกแนบมา](<{message.jump_url}>)**", ephemeral=True)
            return

        search_result = {}
        page_number = {}
        guild = interaction.guild.id

        search_result[guild] = {}
        page_number[guild] = 1

        await interaction.response.send_message(f"<a:MagnifierGIF:1052563354910216252> **[กำลังค้นหาภาพ](<{message.jump_url}>)**")
        searchUrl = 'https://yandex.com/images/search'
        files = {'upfile': ('blob', requests.get(message.attachments[0].url).content, 'image/jpeg')}
        params = {'rpt': 'imageview', 'format': 'json', 'request': '{"blocks":[{"block":"b-page_type_search-by-image__link"}]}'}
        response = requests.post(searchUrl, params=params, files=files)
        query_string = json.loads(response.content)['blocks'][0]['params']['url']
        img_search_url= searchUrl + '?' + query_string

        response = requests.get(img_search_url)
        if response.status_code == 200:
            soup = BeautifulSoup(response.content, 'html.parser')
            cbir_items = soup.find('ul', {'class': 'CbirSites-Items'})
            if cbir_items:
                items = cbir_items.find_all('li', {'class': 'CbirSites-Item'})[:10]
                for index, item in enumerate(items, 1):
                    title = item.find('a', {'class': 'Link_view_default'}).text.strip()
                    link = item.find('a', {'class': 'Link_view_outer'}).get('href')
                    description = item.find('div', {'class': 'CbirSites-ItemDescription'}).text.strip()
                    thumbnail = item.find('img', {'class': 'MMImage Thumb-Image'}).get('src')
                    picture_size = item.find('div', {'class': 'Thumb-Mark Typo Typo_text_s'}).text.strip()
                    
                    if thumbnail is not None:
                        thumbnail_url = thumbnail if thumbnail.startswith('http') else 'https:' + thumbnail
                    else:
                        thumbnail_url = None
                    search_result[guild][index] = [title, link, description, thumbnail_url, picture_size]  

        else:
            print('Failed to fetch the page')

        search = discord.Embed(title = search_result[guild][page_number[guild]][0], color = 0x5be259)
        search.description = search_result[guild][page_number[guild]][2]
        search.add_field(name="**ขนาดภาพ**", value=f'`{search_result[guild][page_number[guild]][4]}`', inline=False)
        search.set_image(url=search_result[guild][page_number[guild]][3])
        search.timestamp = interaction.created_at
        search.set_footer(text=f'Page {page_number[guild]} of {len(search_result[guild])}')

        async def go_next(interaction):
            page_number[guild] += 1
            if page_number[guild] > len(search_result[guild]):
                page_number[guild] = 1
            search = discord.Embed(title = search_result[guild][page_number[guild]][0], color = 0x5be259)
            search.description = search_result[guild][page_number[guild]][2]
            search.add_field(name="**ขนาดภาพ**", value=f'`{search_result[guild][page_number[guild]][4]}`', inline=False)
            search.set_image(url=search_result[guild][page_number[guild]][3])
            search.timestamp = interaction.created_at
            search.set_footer(text=f'Page {page_number[guild]} of {len(search_result[guild])}')
            await interaction.response.defer()
            await interaction.edit_original_response(content=f'🔎 **[ภาพที่ถูกค้นหา](<{message.jump_url}>)**', embed=search, view=url_view)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')

        async def go_previous(interaction):
            page_number[guild] -= 1
            if page_number[guild] < 1:
                page_number[guild] = len(search_result[guild])
            search = discord.Embed(title = search_result[guild][page_number[guild]][0], color = 0x5be259)
            search.description = search_result[guild][page_number[guild]][2]
            search.add_field(name="**ขนาดภาพ**", value=f'`{search_result[guild][page_number[guild]][4]}`', inline=False)
            search.set_image(url=search_result[guild][page_number[guild]][3])
            search.timestamp = interaction.created_at
            search.set_footer(text=f'Page {page_number[guild]} of {len(search_result[guild])}')
            await interaction.response.defer()
            await interaction.edit_original_response(content=f'🔎 **[ภาพที่ถูกค้นหา](<{message.jump_url}>)**', embed=search, view=url_view)
            await self.log_cog.runcomplete('<:Approve:921703512382009354>')

        next_page = discord.ui.Button(label='Next page', emoji="➡️", style=discord.ButtonStyle.primary)
        previous_page = discord.ui.Button(label='Previous page', emoji="⬅️", style=discord.ButtonStyle.primary)
        next_page.callback = go_next
        previous_page.callback = go_previous
        url_view = discord.ui.View()
        url_view.add_item(previous_page)
        url_view.add_item(next_page)
        url_view.add_item(discord.ui.Button(label='Search Result',emoji="🔗",style=discord.ButtonStyle.url, url=img_search_url))
        url_view.add_item(discord.ui.Button(label='Image Source',emoji="🔎",style=discord.ButtonStyle.url, url=search_result[guild][page_number[guild]][1]))
        
        await interaction.edit_original_response(content=f'🔎 **[ภาพที่ถูกค้นหา](<{message.jump_url}>)**' , embed=search, view=url_view)
        await self.log_cog.runcomplete('<:Approve:921703512382009354>')

async def setup(client: commands.Bot):
    print("Setting up SearchByImage cog")
    await client.add_cog(SearchByImage(client))